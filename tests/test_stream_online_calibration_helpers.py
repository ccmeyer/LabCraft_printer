from __future__ import annotations

import json

from tools.stream_analysis import online_calibration as mod


def test_normalize_online_stream_prior_none_returns_default_shape():
    prior = mod.normalize_online_stream_prior(None)

    assert prior == {
        "condition_match": "none",
        "flow_start_offset_us": 650,
        "flow_step_us": 200,
        "flow_delay_count": 5,
        "tail_start_offset_us": 3800,
        "tail_coarse_step_us": 100,
        "source": "default",
        "warnings": [],
    }


def test_normalize_online_stream_prior_partial_input_fills_missing_defaults():
    prior = mod.normalize_online_stream_prior(
        {
            "condition_match": "exact",
            "flow_start_offset_us": 700,
            "warnings": ["used prior"],
        }
    )

    assert prior["condition_match"] == "exact"
    assert prior["flow_start_offset_us"] == 700
    assert prior["flow_step_us"] == 200
    assert prior["flow_delay_count"] == 5
    assert prior["tail_start_offset_us"] == 3800
    assert prior["tail_coarse_step_us"] == 100
    assert prior["source"] == "provided"
    assert prior["warnings"] == ["used prior"]


def test_build_online_stream_flow_plan_uses_exact_condition_prior_without_changing_shape():
    plan = mod.build_online_stream_flow_plan(
        emergence_time_us=1000,
        prior={
            "condition_match": "exact",
            "source": "calibration_memory",
            "flow_start_offset_us": 700,
        },
    )

    assert plan["delay_offsets_from_emergence_us"] == [700, 900, 1100, 1300, 1500]
    assert plan["delays_us"] == [1700, 1900, 2100, 2300, 2500]
    assert plan["replicates_per_delay"] == 3
    assert plan["point_count"] == 5
    assert plan["plan_source"] == "prior_adjusted"


def test_build_online_stream_flow_plan_without_prior_matches_frozen_defaults():
    plan = mod.build_online_stream_flow_plan(emergence_time_us=1000)

    assert plan["delay_offsets_from_emergence_us"] == [650, 850, 1050, 1250, 1450]
    assert plan["delays_us"] == [1650, 1850, 2050, 2250, 2450]
    assert plan["replicates_per_delay"] == 3
    assert plan["point_count"] == 5
    assert plan["plan_source"] == "default"


def test_build_online_stream_tail_plan_without_prior_matches_frozen_defaults():
    plan = mod.build_online_stream_tail_plan(emergence_time_us=1000)

    assert plan["coarse_start_offset_us"] == 3800
    assert plan["coarse_start_delay_us"] == 4800
    assert plan["coarse_step_us"] == 100
    assert plan["coarse_replicates"] == 2
    assert plan["refine_step_us"] == 50
    assert plan["refine_replicates"] == 2
    assert plan["plan_source"] == "default"


def test_build_online_stream_tail_plan_exact_prior_starts_coarse_search_300us_early():
    plan = mod.build_online_stream_tail_plan(
        emergence_time_us=1000,
        prior={
            "condition_match": "exact",
            "tail_start_offset_us": 3950,
            "tail_coarse_step_us": 100,
        },
    )

    assert plan["coarse_start_offset_us"] == 3650
    assert plan["coarse_start_delay_us"] == 4650
    assert plan["coarse_step_us"] == 100
    assert plan["plan_source"] == "exact_prior_minus_lead"


def test_build_online_stream_flow_plan_partial_prior_respects_custom_policy_defaults():
    plan = mod.build_online_stream_flow_plan(
        emergence_time_us=1000,
        prior={"flow_start_offset_us": 700},
        policy={"flow_step_us": 150, "flow_delay_count": 4},
    )

    assert plan["delay_offsets_from_emergence_us"] == [700, 850, 1000, 1150]
    assert plan["delays_us"] == [1700, 1850, 2000, 2150]
    assert plan["point_count"] == 4
    assert plan["plan_source"] == "prior_adjusted"


def test_build_online_stream_tail_plan_partial_prior_respects_custom_policy_defaults():
    plan = mod.build_online_stream_tail_plan(
        emergence_time_us=1000,
        prior={"source": "provided"},
        policy={"tail_fallback_start_offset_us": 4200, "tail_coarse_step_us": 125},
    )

    assert plan["coarse_start_offset_us"] == 4200
    assert plan["coarse_start_delay_us"] == 5200
    assert plan["coarse_step_us"] == 125
    assert plan["plan_source"] == "default"


def test_online_stream_budget_creation_and_consumption_is_non_mutating():
    budget = mod.new_online_stream_budget()

    consumed = mod.consume_online_stream_budget(budget, phase="flow_rate", count=3)

    assert budget["captures_used"] == 0
    assert budget["captures_remaining_nominal"] == 30
    assert budget["captures_remaining_hard"] == 36
    assert budget["history"] == []

    assert consumed["captures_used"] == 3
    assert consumed["captures_remaining_nominal"] == 27
    assert consumed["captures_remaining_hard"] == 33
    assert consumed["exhausted"] is False
    assert consumed["history"][-1]["phase"] == "flow_rate"
    assert consumed["history"][-1]["count"] == 3


def test_online_stream_budget_marks_exhausted_at_hard_limit():
    budget = mod.new_online_stream_budget()

    exhausted = mod.consume_online_stream_budget(budget, phase="tail_start", count=36)

    assert exhausted["captures_used"] == 36
    assert exhausted["captures_remaining_nominal"] == 0
    assert exhausted["captures_remaining_hard"] == 0
    assert exhausted["exhausted"] is True


def test_build_online_stream_frame_row_returns_exact_required_keys_for_accepted_frame():
    row = mod.build_online_stream_frame_row(
        phase="flow_rate",
        status="accepted",
        delay_us=4300,
        delay_from_emergence_us=850,
        replicate_index=2,
        qc={"silhouette": True},
        image_ref={"capture_id": "cap_01"},
        warnings=[],
    )

    assert set(row.keys()) == {
        "phase",
        "status",
        "delay_us",
        "delay_from_emergence_us",
        "replicate_index",
        "qc",
        "image_ref",
        "warnings",
    }
    assert row["status"] == "accepted"


def test_build_online_stream_frame_row_returns_exact_required_keys_for_rejected_frame():
    row = mod.build_online_stream_frame_row(
        phase="tail_start",
        status="rejected",
        delay_us=7800,
        delay_from_emergence_us=4300,
        replicate_index=1,
        qc={"silhouette": False},
        image_ref={},
        warnings=["qc_failed"],
    )

    assert set(row.keys()) == {
        "phase",
        "status",
        "delay_us",
        "delay_from_emergence_us",
        "replicate_index",
        "qc",
        "image_ref",
        "warnings",
    }
    assert row["warnings"] == ["qc_failed"]


def test_build_online_stream_measurement_row_returns_exact_required_keys():
    row = mod.build_online_stream_measurement_row(
        phase="flow_rate",
        delay_us=4300,
        delay_from_emergence_us=850,
        replicate_index=2,
        width_px=91.5,
        visible_volume_nl=12.3,
        qc_pass=True,
        image_ref={"capture_id": "cap_02"},
        nozzle_qc_pass=True,
        silhouette_qc_pass=True,
        attached_bottom_clearance_px=150,
    )

    assert set(row.keys()) == {
        "phase",
        "delay_us",
        "delay_from_emergence_us",
        "replicate_index",
        "width_px",
        "visible_volume_nl",
        "qc_pass",
        "image_ref",
        "nozzle_qc_pass",
        "silhouette_qc_pass",
        "attached_bottom_clearance_px",
    }


def test_build_online_stream_result_stub_returns_exact_top_level_shape():
    result = mod.build_online_stream_result_stub(
        condition={"print_pressure_psi": 0.4},
        priors={"source": "default"},
        flow_phase={"status": "not_run"},
        tail_phase={"status": "not_run"},
        predicted_stream_duration_us=None,
        predicted_volume_nl=None,
        warnings=["stage2_skeleton_no_measurements"],
    )

    assert set(result.keys()) == {
        "condition",
        "priors",
        "flow_phase",
        "tail_phase",
        "predicted_stream_duration_us",
        "predicted_volume_nl",
        "warnings",
    }
    assert result["warnings"] == ["stage2_skeleton_no_measurements"]


def test_build_online_stream_flow_fit_artifact_returns_exact_top_level_shape():
    artifact = mod.build_online_stream_flow_fit_artifact(
        condition={"print_pressure_psi": 0.42},
        flow_plan={"delays_us": [3850, 4050]},
        accepted_delay_points=[{"delay_us": 3850, "median_visible_volume_nl": 12.3}],
        fit={"fit_status": "ok", "flow_rate_nl_per_us": 0.0187, "warnings": ["flow_fit_ok"]},
        warnings=["flow_fit_ok"],
    )

    assert set(artifact.keys()) == {
        "schema_version",
        "phase",
        "condition",
        "flow_plan",
        "accepted_delay_points",
        "fit",
        "warnings",
    }
    assert artifact["fit"]["fit_status"] == "ok"


def test_build_online_stream_flow_phase_payload_appends_fit_fields():
    payload = mod.build_online_stream_flow_phase_payload(
        status="captured",
        plan={"delays_us": [3850, 4050]},
        attempted_delay_count=2,
        attempted_capture_count=6,
        accepted_delay_count=2,
        accepted_measurement_count=4,
        rejected_capture_count=2,
        termination_reason="planned_delays_exhausted",
        delay_summaries=[{"delay_us": 3850}],
        warnings=["detached_near_bottom_warning"],
        fit={
            "fit_status": "ok",
            "flow_rate_nl_per_us": 0.0187,
            "flow_intercept_nl": -1.2,
            "flow_fit_delay_start_from_emergence_us": 650,
            "flow_fit_delay_end_from_emergence_us": 1450,
            "steady_width_baseline_px": 74.0,
            "steady_r2": 0.998,
            "steady_nrmse": 0.01,
            "steady_rate_ci95_low_nl_per_us": 0.0185,
            "steady_rate_ci95_high_nl_per_us": 0.0189,
            "steady_rate_ci95_relative_width": 0.02,
            "flow_fit_point_count": 5,
            "flow_fit_outlier_prune_status": "kept_below_local_deviation_threshold",
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "warnings": ["flow_fit_min_points_only"],
        },
    )

    assert payload["status"] == "captured"
    assert payload["flow_rate_nl_per_us"] == 0.0187
    assert payload["steady_width_baseline_px"] == 74.0
    assert payload["flow_fit_point_count"] == 5
    assert payload["fit_warnings"] == ["flow_fit_min_points_only"]


def test_build_online_stream_plan_snapshot_returns_exact_top_level_shape():
    snapshot = mod.build_online_stream_plan_snapshot(
        condition={"print_pressure_psi": 0.42},
        priors={"source": "default"},
        flow_plan={"delays_us": [3850, 4050]},
        tail_plan={"coarse_start_delay_us": 7000},
        capture_budget={"captures_used": 0},
        analysis_config={"nozzle_guard_px": 2},
    )

    assert set(snapshot.keys()) == {
        "schema_version",
        "phase",
        "condition",
        "priors",
        "flow_plan",
        "tail_plan",
        "capture_budget",
        "analysis_config",
    }
    assert snapshot["phase"] == "online_stream_calibration"
    assert snapshot["analysis_config"]["nozzle_guard_px"] == 2
    assert snapshot["analysis_config"]["attached_bottom_guard_px"] == 96


def test_build_online_stream_prior_resolution_artifact_returns_exact_top_level_shape():
    artifact = mod.build_online_stream_prior_resolution_artifact(
        condition={"print_pressure_psi": 0.42},
        lookup={"looked_up": True, "candidate_found": True},
        candidate_prior={"source": "calibration_memory"},
        applied_prior={"source": "calibration_memory", "flow_start_offset_us": 700},
        fallback_reason=None,
        warnings=["prior_applied"],
    )

    assert set(artifact.keys()) == {
        "schema_version",
        "phase",
        "condition",
        "lookup",
        "candidate_prior",
        "applied_prior",
        "fallback_reason",
        "warnings",
    }
    assert artifact["lookup"]["candidate_found"] is True


def test_summarize_online_stream_flow_delay_computes_medians_and_counts():
    summary = mod.summarize_online_stream_flow_delay(
        [
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="accepted",
                delay_us=4050,
                delay_from_emergence_us=850,
                replicate_index=1,
                qc={"measurement_qc_pass": True},
                image_ref={"capture_id": "cap_01"},
                warnings=[],
                attached_width_px=90.0,
                visible_volume_nl=10.0,
                attached_bottom_clearance_px=150,
                detached_near_bottom_warning=False,
            ),
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="accepted",
                delay_us=4050,
                delay_from_emergence_us=850,
                replicate_index=2,
                qc={"measurement_qc_pass": True},
                image_ref={"capture_id": "cap_02"},
                warnings=["detached_near_bottom_warning"],
                attached_width_px=92.0,
                visible_volume_nl=12.0,
                attached_bottom_clearance_px=145,
                detached_near_bottom_warning=True,
            ),
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="rejected_silhouette_qc",
                delay_us=4050,
                delay_from_emergence_us=850,
                replicate_index=3,
                qc={"measurement_qc_pass": False},
                image_ref={"capture_id": "cap_03"},
                warnings=["silhouette_qc_failed"],
                attached_width_px=None,
                visible_volume_nl=None,
                attached_bottom_clearance_px=140,
                detached_near_bottom_warning=False,
            ),
        ]
    )

    assert summary["delay_us"] == 4050
    assert summary["attempted_replicates"] == 3
    assert summary["accepted_replicates"] == 2
    assert summary["rejected_replicates"] == 1
    assert summary["median_visible_volume_nl"] == 11.0
    assert summary["median_width_px"] == 91.0
    assert summary["min_attached_bottom_clearance_px"] == 140.0
    assert summary["detached_near_bottom_warning"] is True
    assert summary["delay_accepted"] is True


def test_summarize_online_stream_flow_delay_marks_bottom_guard_hits():
    summary = mod.summarize_online_stream_flow_delay(
        [
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="rejected_bottom_guard",
                delay_us=4250,
                delay_from_emergence_us=1050,
                replicate_index=1,
                qc={"measurement_qc_pass": False},
                image_ref={"capture_id": "cap_bg"},
                warnings=["attached_bottom_guard_hit"],
                attached_width_px=88.0,
                visible_volume_nl=13.5,
                attached_bottom_clearance_px=96,
                detached_near_bottom_warning=False,
            )
        ]
    )

    assert summary["accepted_replicates"] == 0
    assert summary["attached_bottom_guard_hit"] is True


def test_decide_online_stream_flow_next_action_continue_case():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"delay_accepted": True, "attached_bottom_guard_hit": False},
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=2,
        planned_delay_count=5,
    )

    assert decision == {"action": "continue", "termination_reason": None}


def test_decide_online_stream_flow_next_action_stops_for_attached_bottom_guard():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"attached_bottom_guard_hit": True},
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=1,
        planned_delay_count=5,
    )

    assert decision == {
        "action": "stop",
        "termination_reason": "attached_bottom_guard_hit",
    }


def test_decide_online_stream_flow_next_action_stops_for_repeated_failed_delays():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"attached_bottom_guard_hit": False},
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=2,
        attempted_delay_count=2,
        planned_delay_count=5,
    )

    assert decision == {
        "action": "stop",
        "termination_reason": "repeated_qc_failure",
    }


def test_decide_online_stream_flow_next_action_stops_for_budget_exhaustion():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"attached_bottom_guard_hit": False},
        capture_budget=mod.consume_online_stream_budget(
            mod.new_online_stream_budget(),
            phase="flow_rate",
            count=36,
        ),
        consecutive_failed_delays=0,
        attempted_delay_count=2,
        planned_delay_count=5,
    )

    assert decision == {
        "action": "stop",
        "termination_reason": "capture_budget_exhausted",
    }


def test_decide_online_stream_flow_next_action_stops_when_planned_delays_exhausted():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"attached_bottom_guard_hit": False},
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=5,
        planned_delay_count=5,
    )

    assert decision == {
        "action": "stop",
        "termination_reason": "planned_delays_exhausted",
    }


def test_online_stream_helper_outputs_are_json_serializable():
    payload = {
        "prior": mod.normalize_online_stream_prior(None),
        "flow_plan": mod.build_online_stream_flow_plan(emergence_time_us=1000),
        "tail_plan": mod.build_online_stream_tail_plan(emergence_time_us=1000),
        "budget": mod.consume_online_stream_budget(
            mod.new_online_stream_budget(),
            phase="flow_rate",
            count=2,
        ),
        "frame": mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4300,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"silhouette": True},
            image_ref={"capture_id": "cap_03"},
            warnings=[],
        ),
        "measurement": mod.build_online_stream_measurement_row(
            phase="flow_rate",
            delay_us=4300,
            delay_from_emergence_us=850,
            replicate_index=1,
            width_px=90.0,
            visible_volume_nl=10.5,
            qc_pass=True,
            image_ref={"capture_id": "cap_03"},
        ),
        "plan_snapshot": mod.build_online_stream_plan_snapshot(
            condition={"print_pressure_psi": 0.4},
            priors={"source": "default"},
            flow_plan={"delays_us": [3850, 4050]},
            tail_plan={"coarse_start_delay_us": 7000},
            capture_budget={"captures_used": 2},
            analysis_config={"nozzle_guard_px": 2},
        ),
        "delay_summary": mod.summarize_online_stream_flow_delay(
            [
                mod.build_online_stream_frame_row(
                    phase="flow_rate",
                    status="accepted",
                    delay_us=4300,
                    delay_from_emergence_us=850,
                    replicate_index=1,
                    qc={"measurement_qc_pass": True},
                    image_ref={"capture_id": "cap_03"},
                    warnings=[],
                    attached_width_px=90.0,
                    visible_volume_nl=10.5,
                    attached_bottom_clearance_px=150,
                    detached_near_bottom_warning=False,
                )
            ]
        ),
        "decision": mod.decide_online_stream_flow_next_action(
            delay_summary={"attached_bottom_guard_hit": False},
            capture_budget=mod.new_online_stream_budget(),
            consecutive_failed_delays=0,
            attempted_delay_count=1,
            planned_delay_count=5,
        ),
        "result": mod.build_online_stream_result_stub(
            condition={"print_pressure_psi": 0.4},
            priors={"source": "default"},
            flow_phase={"status": "not_run"},
            tail_phase={"status": "not_run"},
            warnings=["stage2_skeleton_no_measurements"],
        ),
        "flow_fit_artifact": mod.build_online_stream_flow_fit_artifact(
            condition={"print_pressure_psi": 0.4},
            flow_plan={"delays_us": [3850, 4050]},
            accepted_delay_points=[{"delay_us": 3850, "median_visible_volume_nl": 12.3}],
            fit={"fit_status": "ok", "flow_rate_nl_per_us": 0.0187},
            warnings=["flow_fit_ok"],
        ),
        "flow_phase_payload": mod.build_online_stream_flow_phase_payload(
            status="captured",
            plan={"delays_us": [3850, 4050]},
            attempted_delay_count=2,
            attempted_capture_count=6,
            accepted_delay_count=2,
            accepted_measurement_count=4,
            rejected_capture_count=2,
            termination_reason="planned_delays_exhausted",
            delay_summaries=[{"delay_us": 3850}],
            warnings=["detached_near_bottom_warning"],
            fit={"fit_status": "ok", "flow_rate_nl_per_us": 0.0187, "flow_fit_point_count": 5},
        ),
    }

    encoded = json.dumps(payload)

    assert isinstance(encoded, str)
    assert "stage2_skeleton_no_measurements" in encoded
