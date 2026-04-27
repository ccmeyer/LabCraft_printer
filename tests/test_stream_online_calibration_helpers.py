from __future__ import annotations

import json

from tools.stream_analysis import online_calibration as mod


def test_normalize_online_stream_prior_none_returns_default_shape():
    prior = mod.normalize_online_stream_prior(None)

    assert prior == {
        "condition_match": "none",
        "flow_start_offset_us": 650,
        "flow_step_us": 57,
        "flow_delay_count": 15,
        "tail_start_offset_us": 3600,
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
    assert prior["flow_step_us"] == 57
    assert prior["flow_delay_count"] == 15
    assert prior["tail_start_offset_us"] == 3600
    assert prior["tail_coarse_step_us"] == 100
    assert prior["source"] == "provided"
    assert prior["warnings"] == ["used prior"]


def test_build_online_stream_flow_plan_uses_exact_condition_prior_without_changing_adaptive_policy():
    plan = mod.build_online_stream_flow_plan(
        emergence_time_us=1000,
        prior={
            "condition_match": "exact",
            "source": "calibration_memory",
            "flow_start_offset_us": 700,
        },
    )

    assert plan["search_method"] == "adaptive_visible_span_v1"
    assert plan["start_offset_from_emergence_us"] == 700
    assert plan["start_delay_us"] == 1700
    assert plan["delay_offsets_from_emergence_us"] == [700]
    assert plan["delays_us"] == [1700]
    assert plan["replicates_per_delay"] == 1
    assert plan["point_count"] == 20
    assert plan["scout_step_us"] == 100
    assert plan["min_accepted_delays"] == 12
    assert plan["max_capture_count"] == 30
    assert plan["late_coverage_min_delay_us"] == 2250
    assert plan["late_coverage_min_visible_fluid_clearance_px"] == 300
    assert plan["late_coverage_confidence_min"] == 0.70
    assert plan["reserved_tail_capture_count"] == 25
    assert plan["plan_source"] == "prior_adjusted"


def test_build_online_stream_flow_plan_without_prior_matches_adaptive_defaults():
    plan = mod.build_online_stream_flow_plan(emergence_time_us=1000)

    assert plan["search_method"] == "adaptive_visible_span_v1"
    assert plan["start_offset_from_emergence_us"] == 650
    assert plan["start_delay_us"] == 1650
    assert plan["delay_offsets_from_emergence_us"] == [650]
    assert plan["delays_us"] == [1650]
    assert plan["replicates_per_delay"] == 1
    assert plan["point_count"] == 20
    assert plan["scout_step_us"] == 100
    assert plan["min_accepted_delays"] == 12
    assert plan["max_capture_count"] == 30
    assert plan["soft_bottom_clearance_px"] == 150
    assert plan["ci95_relative_width_target"] == 0.12
    assert plan["late_coverage_min_delay_us"] == 2250
    assert plan["late_coverage_min_visible_fluid_clearance_px"] == 300
    assert plan["late_coverage_confidence_min"] == 0.70
    assert plan["reserved_tail_capture_count"] == 25
    assert plan["plan_source"] == "default"


def test_build_online_stream_flow_plan_ignores_legacy_prior_shape_and_keeps_only_start_offset():
    plan = mod.build_online_stream_flow_plan(
        emergence_time_us=1000,
        prior={
            "condition_match": "exact",
            "flow_start_offset_us": 700,
            "flow_step_us": 200,
            "flow_delay_count": 5,
        },
    )

    assert plan["start_offset_from_emergence_us"] == 700
    assert plan["delay_offsets_from_emergence_us"] == [700]
    assert plan["replicates_per_delay"] == 1
    assert plan["point_count"] == 20


def test_build_online_stream_tail_plan_without_prior_matches_frozen_defaults():
    plan = mod.build_online_stream_tail_plan(emergence_time_us=1000)

    assert plan["coarse_start_offset_us"] == 3600
    assert plan["coarse_start_delay_us"] == 4600
    assert plan["coarse_step_us"] == 100
    assert plan["coarse_replicates"] == 2
    assert plan["refine_step_us"] == 50
    assert plan["refine_replicates"] == 2
    assert plan["plan_source"] == "default"


def test_build_online_stream_tail_plan_exact_prior_starts_coarse_search_400us_early():
    plan = mod.build_online_stream_tail_plan(
        emergence_time_us=1000,
        prior={
            "condition_match": "exact",
            "tail_start_offset_us": 3950,
            "tail_coarse_step_us": 100,
        },
    )

    assert plan["coarse_start_offset_us"] == 3550
    assert plan["coarse_start_delay_us"] == 4550
    assert plan["coarse_step_us"] == 100
    assert plan["plan_source"] == "exact_prior_minus_lead"


def test_build_online_stream_flow_plan_partial_prior_respects_custom_policy_defaults():
    plan = mod.build_online_stream_flow_plan(
        emergence_time_us=1000,
        prior={"flow_start_offset_us": 700},
        policy={
            "flow_target_delay_count": 4,
            "flow_scout_step_us": 150,
            "flow_min_accepted_delays": 3,
            "flow_max_capture_count": 8,
        },
    )

    assert plan["delay_offsets_from_emergence_us"] == [700]
    assert plan["delays_us"] == [1700]
    assert plan["point_count"] == 4
    assert plan["scout_step_us"] == 150
    assert plan["min_accepted_delays"] == 3
    assert plan["max_capture_count"] == 8
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
    assert budget["captures_remaining_nominal"] == 55
    assert budget["captures_remaining_hard"] == 61
    assert budget["history"] == []

    assert consumed["captures_used"] == 3
    assert consumed["captures_remaining_nominal"] == 52
    assert consumed["captures_remaining_hard"] == 58
    assert consumed["exhausted"] is False
    assert consumed["history"][-1]["phase"] == "flow_rate"
    assert consumed["history"][-1]["count"] == 3


def test_online_stream_budget_marks_exhausted_at_hard_limit():
    budget = mod.new_online_stream_budget()

    exhausted = mod.consume_online_stream_budget(budget, phase="tail_start", count=61)

    assert exhausted["captures_used"] == 61
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
        "min_accepted_fluid_distance_from_bottom_px",
        "flow_geometry_confidence",
        "flow_optical_confidence",
        "flow_point_confidence",
        "flow_optical_confidence_active",
        "optical_activation_clearance_px",
        "lower_edge_jitter_px",
        "boundary_chroma_aberration_score",
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
        "learned_flow_start_offset_us",
        "learned_tail_start_offset_us",
        "warnings",
    }
    assert result["warnings"] == ["stage2_skeleton_no_measurements"]


def test_build_online_stream_flow_fit_artifact_returns_exact_top_level_shape():
    artifact = mod.build_online_stream_flow_fit_artifact(
        condition={"print_pressure_psi": 0.42},
        flow_plan={"delays_us": [3850, 4050]},
        delay_summaries=[{"delay_us": 3850, "flow_volume_geometry_ok": True}],
        accepted_delay_points=[{"delay_us": 3850, "median_visible_volume_nl": 12.3}],
        fit={"fit_status": "ok", "flow_rate_nl_per_us": 0.0187, "warnings": ["flow_fit_ok"]},
        warnings=["flow_fit_ok"],
    )

    assert set(artifact.keys()) == {
        "schema_version",
        "phase",
        "condition",
        "flow_plan",
        "delay_summaries",
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
            "lag_equivalent_us": 64.2,
            "flow_fit_delay_start_from_emergence_us": 650,
            "flow_fit_delay_end_from_emergence_us": 1450,
            "steady_width_baseline_px": 74.0,
            "steady_r2": 0.998,
            "steady_nrmse": 0.01,
            "steady_rate_ci95_low_nl_per_us": 0.0185,
            "steady_rate_ci95_high_nl_per_us": 0.0189,
            "steady_rate_ci95_relative_width": 0.02,
            "late_slope_nl_per_us": 0.0188,
            "late_slope_relative_gap": 0.03,
            "late_slope_stable": True,
            "late_coverage_reached": True,
            "late_coverage_delay_from_emergence_us": 2350,
            "late_coverage_metric": "visible_fluid_bottom_clearance",
            "fit_weight_floor": 0.20,
            "flow_fit_point_count": 5,
            "flow_fit_outlier_prune_status": "kept_below_local_deviation_threshold",
            "flow_fit_dropped_outlier_delay_from_emergence_us": None,
            "warnings": ["flow_fit_min_points_only"],
        },
        search_boundary_deferred_reason="detached_geometry_precoverage",
        confidence_boundary_delay_from_emergence_us=2150,
    )

    assert payload["status"] == "captured"
    assert payload["flow_rate_nl_per_us"] == 0.0187
    assert payload["lag_equivalent_us"] == 64.2
    assert payload["steady_width_baseline_px"] == 74.0
    assert payload["late_slope_stable"] is True
    assert payload["late_coverage_metric"] == "visible_fluid_bottom_clearance"
    assert payload["search_boundary_deferred_reason"] == "detached_geometry_precoverage"
    assert payload["confidence_boundary_delay_from_emergence_us"] == 2150
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


def test_summarize_online_stream_flow_delay_tracks_confidence_and_visible_fluid_clearance():
    summary = mod.summarize_online_stream_flow_delay(
        [
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="accepted",
                delay_us=5450,
                delay_from_emergence_us=2250,
                replicate_index=1,
                qc={"measurement_qc_pass": True},
                image_ref={"capture_id": "cap_late_01"},
                warnings=[],
                attached_width_px=91.0,
                visible_volume_nl=18.0,
                attached_bottom_clearance_px=420,
                min_accepted_fluid_distance_from_bottom_px=280,
                detached_near_bottom_warning=False,
                flow_geometry_confidence=0.88,
                flow_optical_confidence=0.74,
                flow_point_confidence=0.74,
                flow_optical_confidence_active=True,
                optical_activation_clearance_px=400,
                lower_edge_jitter_px=0.8,
                boundary_chroma_aberration_score=11.0,
            )
        ]
    )

    assert summary["min_accepted_fluid_distance_from_bottom_px"] == 280.0
    assert summary["flow_geometry_confidence"] == 0.88
    assert summary["flow_optical_confidence"] == 0.74
    assert summary["flow_point_confidence"] == 0.74
    assert summary["flow_optical_confidence_active"] is True
    assert summary["optical_activation_clearance_px"] == 400.0
    assert summary["late_coverage_candidate"] is True
    assert summary["late_coverage_metric"] == "delay_threshold"


def test_online_stream_late_coverage_candidate_uses_visible_fluid_clearance_when_detached_fluid_reaches_bottom():
    candidate, metric = mod.is_online_stream_flow_late_coverage_candidate(
        {
            "delay_accepted": True,
            "delay_from_emergence_us": 2050,
            "flow_point_confidence": 0.76,
            "min_accepted_fluid_distance_from_bottom_px": 280,
            "min_attached_bottom_clearance_px": 420,
        }
    )

    assert candidate is True
    assert metric == "visible_fluid_bottom_clearance"


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


def test_summarize_online_stream_flow_delay_excludes_geometry_rejected_rows_from_acceptance():
    summary = mod.summarize_online_stream_flow_delay(
        [
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="accepted",
                delay_us=4250,
                delay_from_emergence_us=1050,
                replicate_index=1,
                qc={"measurement_qc_pass": True},
                image_ref={"capture_id": "cap_geom"},
                warnings=["flow_volume_geometry_not_ok"],
                attached_width_px=88.0,
                visible_volume_nl=13.5,
                attached_bottom_clearance_px=140,
                detached_near_bottom_warning=False,
                flow_volume_geometry_ok=False,
                flow_volume_geometry_reasons=["attached_lower_centerline_span_high"],
                flow_measurement_usable=False,
            )
        ]
    )

    assert summary["accepted_replicates"] == 0
    assert summary["geometry_rejected_replicates"] == 1
    assert summary["geometry_boundary_triggered"] is True
    assert summary["flow_volume_geometry_ok"] is False
    assert summary["flow_volume_geometry_reasons"] == ["attached_lower_centerline_span_high"]
    assert summary["geometry_boundary_scope"] == "attached"


def test_summarize_online_stream_flow_delay_accepts_geometry_warning_rows():
    summary = mod.summarize_online_stream_flow_delay(
        [
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="accepted",
                delay_us=4250,
                delay_from_emergence_us=1050,
                replicate_index=1,
                qc={"measurement_qc_pass": True},
                image_ref={"capture_id": "cap_geom_warn"},
                warnings=[],
                attached_width_px=88.0,
                visible_volume_nl=13.5,
                attached_bottom_clearance_px=420,
                detached_near_bottom_warning=False,
                flow_volume_geometry_ok=True,
                flow_volume_geometry_warnings=["attached_lower_centerline_span_high"],
                flow_measurement_usable=True,
            )
        ]
    )

    assert summary["accepted_replicates"] == 1
    assert summary["geometry_rejected_replicates"] == 0
    assert summary["geometry_boundary_triggered"] is False
    assert summary["flow_volume_geometry_ok"] is True
    assert summary["flow_volume_geometry_reasons"] == []
    assert summary["flow_volume_geometry_warnings"] == ["attached_lower_centerline_span_high"]
    assert "attached_lower_centerline_span_high" in summary["warnings"]


def test_summarize_online_stream_flow_delay_excludes_volume_incomplete_rows_from_acceptance():
    summary = mod.summarize_online_stream_flow_delay(
        [
            mod.build_online_stream_frame_row(
                phase="flow_rate",
                status="accepted",
                delay_us=4250,
                delay_from_emergence_us=1050,
                replicate_index=1,
                qc={"measurement_qc_pass": True},
                image_ref={"capture_id": "cap_incomplete"},
                warnings=["flow_volume_incomplete"],
                attached_width_px=88.0,
                visible_volume_nl=13.5,
                attached_bottom_clearance_px=140,
                detached_near_bottom_warning=False,
                flow_volume_geometry_ok=True,
                flow_volume_complete_ok=False,
                flow_volume_completeness_reasons=["material_plausible_unaccepted_detached"],
                plausible_unaccepted_component_count=1,
                plausible_unaccepted_visible_volume_nl=1.4,
                flow_measurement_usable=False,
            )
        ]
    )

    assert summary["accepted_replicates"] == 0
    assert summary["volume_incomplete_rejected_replicates"] == 1
    assert summary["flow_volume_complete_ok"] is False
    assert summary["flow_volume_completeness_reasons"] == ["material_plausible_unaccepted_detached"]
    assert summary["plausible_unaccepted_component_count"] == 1
    assert summary["plausible_unaccepted_visible_volume_nl"] == 1.4


def test_online_stream_flow_geometry_boundary_helper_detects_geometry_failures():
    assert mod.is_online_stream_flow_geometry_boundary(
        {"geometry_boundary_triggered": True}
    ) is True
    assert mod.is_online_stream_flow_geometry_boundary(
        {"flow_volume_geometry_ok": False}
    ) is True
    assert mod.is_online_stream_flow_geometry_boundary(
        {"flow_volume_geometry_ok": True}
    ) is False


def test_flow_geometry_boundary_scope_classifies_attached_detached_mixed_and_unknown():
    assert mod.flow_geometry_boundary_scope(
        {
            "flow_volume_geometry_ok": False,
            "flow_volume_geometry_reasons": ["attached_lower_centerline_span_high"],
        }
    ) == "attached"
    assert mod.flow_geometry_boundary_scope(
        {
            "flow_volume_geometry_ok": False,
            "flow_volume_geometry_reasons": ["detached_01:detached_local_centerline_span_high"],
        }
    ) == "detached_only"
    assert mod.flow_geometry_boundary_scope(
        {
            "flow_volume_geometry_ok": False,
            "flow_volume_geometry_reasons": [
                "attached_lower_centerline_span_high",
                "detached_01:detached_local_centerline_span_high",
            ],
        }
    ) == "mixed"
    assert mod.flow_geometry_boundary_scope(
        {
            "flow_volume_geometry_ok": False,
            "flow_volume_geometry_reasons": ["geometry_shape_unknown"],
        }
    ) == "unknown"
    assert mod.flow_geometry_boundary_scope({"flow_volume_geometry_ok": True}) == "none"


def test_online_stream_flow_search_boundary_defers_attached_and_detached_only_failures_until_late_coverage():
    detached_only = {
        "flow_volume_geometry_ok": False,
        "flow_volume_geometry_reasons": ["detached_01:detached_local_centerline_span_high"],
    }
    attached_only = {
        "flow_volume_geometry_ok": False,
        "flow_volume_geometry_reasons": ["attached_lower_centerline_span_high"],
    }
    assert mod.is_online_stream_flow_search_boundary(
        detached_only,
        late_coverage_reached=False,
    ) is False
    assert mod.is_online_stream_flow_search_boundary(
        detached_only,
        late_coverage_reached=True,
    ) is True
    assert mod.is_online_stream_flow_search_boundary(
        attached_only,
        late_coverage_reached=False,
    ) is False
    assert mod.is_online_stream_flow_search_boundary(
        attached_only,
        late_coverage_reached=True,
    ) is True
    assert mod.is_online_stream_flow_search_boundary(
        {
            "flow_volume_geometry_ok": False,
            "flow_volume_geometry_reasons": [
                "attached_lower_centerline_span_high",
                "detached_01:detached_local_centerline_span_high",
            ],
        },
        late_coverage_reached=False,
    ) is True
    assert mod.is_online_stream_flow_search_boundary(
        {
            "flow_volume_geometry_ok": False,
            "flow_volume_geometry_reasons": ["geometry_shape_unknown"],
        },
        late_coverage_reached=False,
    ) is True


def test_decide_online_stream_flow_next_action_continue_case():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"delay_accepted": True, "attached_bottom_guard_hit": False},
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=2,
        planned_delay_count=15,
        accepted_delay_count=10,
        remaining_delay_count=5,
    )

    assert decision == {"action": "continue", "termination_reason": None}


def test_decide_online_stream_flow_next_action_does_not_stop_for_attached_bottom_guard_on_its_own():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"attached_bottom_guard_hit": True},
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=1,
        planned_delay_count=15,
        accepted_delay_count=11,
        remaining_delay_count=4,
    )

    assert decision == {"action": "continue", "termination_reason": None}


def test_decide_online_stream_flow_next_action_continues_after_single_failed_delay_when_budget_allows():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={
            "attached_bottom_guard_hit": False,
            "attempted_replicates": 1,
            "accepted_replicates": 0,
            "delay_accepted": False,
        },
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=2,
        planned_delay_count=15,
        accepted_delay_count=1,
        remaining_delay_count=13,
    )

    assert decision == {"action": "continue", "termination_reason": None}


def test_decide_online_stream_flow_next_action_stops_for_insufficient_accepted_delays():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={
            "attached_bottom_guard_hit": False,
            "attempted_replicates": 3,
            "accepted_replicates": 1,
            "delay_accepted": True,
        },
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=4,
        planned_delay_count=5,
        accepted_delay_count=1,
        remaining_delay_count=1,
    )

    assert decision == {
        "action": "stop",
        "termination_reason": "insufficient_accepted_delays",
    }


def test_decide_online_stream_flow_next_action_stops_for_budget_exhaustion():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={"attached_bottom_guard_hit": False},
        capture_budget=mod.consume_online_stream_budget(
            mod.new_online_stream_budget(),
            phase="flow_rate",
            count=61,
        ),
        consecutive_failed_delays=0,
        attempted_delay_count=2,
        planned_delay_count=5,
    )

    assert decision == {
        "action": "stop",
        "termination_reason": "hard_budget_exhausted",
    }


def test_decide_online_stream_flow_next_action_stops_when_planned_delays_exhausted():
    decision = mod.decide_online_stream_flow_next_action(
        delay_summary={
            "attached_bottom_guard_hit": False,
            "attempted_replicates": 3,
            "accepted_replicates": 1,
            "delay_accepted": True,
        },
        capture_budget=mod.new_online_stream_budget(),
        consecutive_failed_delays=0,
        attempted_delay_count=5,
        planned_delay_count=5,
        accepted_delay_count=12,
        remaining_delay_count=0,
    )

    assert decision == {
        "action": "stop",
        "termination_reason": "planned_delays_exhausted",
    }


def test_build_online_stream_flow_target_offsets_evenly_spreads_across_visible_span():
    offsets = mod.build_online_stream_flow_target_offsets(
        start_offset_us=650,
        end_offset_us=1450,
        target_delay_count=15,
    )

    assert offsets[0] == 650
    assert offsets[-1] == 1450
    assert len(offsets) == 15
    assert offsets == sorted(set(offsets))


def test_build_online_stream_flow_missing_offsets_reuses_already_sampled_points():
    missing = mod.build_online_stream_flow_missing_offsets(
        target_offsets_from_emergence_us=[650, 750, 850, 950],
        existing_offsets_from_emergence_us=[650, 850],
    )

    assert missing == [750, 950]


def test_select_online_stream_flow_gap_midpoint_picks_largest_safe_gap():
    midpoint = mod.select_online_stream_flow_gap_midpoint(
        sampled_offsets_from_emergence_us=[650, 850, 1050, 1250],
        start_offset_us=650,
        end_offset_us=1450,
    )

    assert midpoint == 750


def test_online_stream_flow_boundary_helpers_distinguish_soft_and_hard_boundaries():
    soft_summary = {
        "delay_accepted": True,
        "detached_near_bottom_warning": False,
        "min_attached_bottom_clearance_px": 145,
        "attached_bottom_guard_hit": False,
    }
    hard_summary = {
        "delay_accepted": False,
        "detached_near_bottom_warning": False,
        "min_attached_bottom_clearance_px": 96,
        "attached_bottom_guard_hit": True,
    }

    assert mod.is_online_stream_flow_soft_boundary(soft_summary) is True
    assert mod.is_online_stream_flow_hard_boundary(soft_summary) is False
    assert mod.is_online_stream_flow_soft_boundary(hard_summary) is False
    assert mod.is_online_stream_flow_hard_boundary(hard_summary) is True


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
            delay_summaries=[{"delay_us": 3850, "flow_volume_geometry_ok": True}],
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
