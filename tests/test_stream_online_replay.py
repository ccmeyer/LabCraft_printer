from __future__ import annotations

import json
from pathlib import Path

from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import online_fit as online_fit_mod
from tools.stream_analysis import online_replay as online_replay_mod
from tools.stream_analysis import online_tail as online_tail_mod


def _write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]):
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def _build_consistent_run(run_dir: Path):
    run_dir.mkdir(parents=True, exist_ok=True)
    condition = {
        "print_pressure_psi": 1.61,
        "print_pulse_width_us": 1500,
        "emergence_time_us": 3200,
        "stock_solution": "Water",
        "printer_head_id": "PH-001",
    }
    priors = {
        "lookup_performed": True,
        "candidate_found": True,
        "source": "calibration_memory",
        "aggregation_level": "exact_pair",
        "pulse_match_type": "exact",
        "condition_match": "exact",
        "source_run_ids": ["seed_run_01"],
        "applied_flow_start_offset_us": 650,
        "applied_flow_step_us": 200,
        "applied_flow_delay_count": 5,
        "applied_tail_start_offset_us": 3950,
        "applied_tail_coarse_step_us": 100,
        "fallback_reason": None,
        "warnings": [],
    }
    flow_plan = {
        "emergence_time_us": 3200,
        "delay_offsets_from_emergence_us": [650, 850, 1050],
        "delays_us": [3850, 4050, 4250],
        "replicates_per_delay": 1,
        "point_count": 3,
        "plan_source": "prior_adjusted",
    }
    tail_plan = {
        "run_tail": True,
        "steady_width_baseline_px": 74.0,
        "coarse_start_delay_us": 7000,
        "coarse_step_us": 100,
        "coarse_replicates": 1,
        "refine_step_us": 50,
        "refine_replicates": 1,
        "planned_coarse_delay_count": 2,
        "reserved_refine_capture_count": 1,
        "plan_source": "exact_prior_minus_lead",
    }
    flow_rows = [
        online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=3850,
            delay_from_emergence_us=650,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "flow_01"},
            warnings=[],
            attached_width_px=74.5,
            visible_volume_nl=12.0,
            attached_bottom_clearance_px=180,
            min_accepted_fluid_distance_from_bottom_px=180,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
        ),
        online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4050,
            delay_from_emergence_us=850,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "flow_02"},
            warnings=[],
            attached_width_px=74.0,
            visible_volume_nl=15.7,
            attached_bottom_clearance_px=165,
            min_accepted_fluid_distance_from_bottom_px=165,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
        ),
        online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=4250,
            delay_from_emergence_us=1050,
            replicate_index=1,
            qc={"measurement_qc_pass": True},
            image_ref={"capture_id": "flow_03"},
            warnings=[],
            attached_width_px=73.5,
            visible_volume_nl=19.4,
            attached_bottom_clearance_px=150,
            min_accepted_fluid_distance_from_bottom_px=150,
            accepted_component_count=1,
            accepted_detached_component_count=0,
            detached_near_bottom_warning=False,
            attached_bottom_guard_hit=False,
        ),
    ]
    flow_measurements = [
        online_cal_mod.build_online_stream_measurement_row(
            phase="flow_rate",
            delay_us=row["delay_us"],
            delay_from_emergence_us=row["delay_from_emergence_us"],
            replicate_index=row["replicate_index"],
            width_px=row["attached_width_px"],
            visible_volume_nl=row["visible_volume_nl"],
            qc_pass=True,
            image_ref=row["image_ref"],
            nozzle_qc_pass=True,
            silhouette_qc_pass=True,
            attached_bottom_clearance_px=row["attached_bottom_clearance_px"],
        )
        for row in flow_rows
    ]
    flow_delay_summaries = [
        online_cal_mod.summarize_online_stream_flow_delay([row])
        for row in flow_rows
    ]
    flow_fit = online_fit_mod.fit_online_stream_flow_phase(
        measurements=flow_measurements,
        delay_summaries=flow_delay_summaries,
    )
    tail_rows = [
        online_cal_mod.build_online_stream_frame_row(
            phase="tail_coarse",
            status="accepted",
            delay_us=7000,
            delay_from_emergence_us=3800,
            replicate_index=1,
            qc={"tail_qc_pass": True},
            image_ref={"capture_id": "tail_c_01"},
            warnings=[],
            attached_width_px=72.0,
        ),
        online_cal_mod.build_online_stream_frame_row(
            phase="tail_coarse",
            status="accepted",
            delay_us=7200,
            delay_from_emergence_us=4000,
            replicate_index=1,
            qc={"tail_qc_pass": True},
            image_ref={"capture_id": "tail_c_02"},
            warnings=[],
            attached_width_px=66.0,
        ),
        online_cal_mod.build_online_stream_frame_row(
            phase="tail_refine",
            status="accepted",
            delay_us=7150,
            delay_from_emergence_us=3950,
            replicate_index=1,
            qc={"tail_qc_pass": True},
            image_ref={"capture_id": "tail_r_01"},
            warnings=[],
            attached_width_px=69.5,
        ),
    ]
    coarse_summaries = [
        online_tail_mod.summarize_online_stream_tail_delay([tail_rows[0]], baseline_width_px=flow_fit["steady_width_baseline_px"]),
        online_tail_mod.summarize_online_stream_tail_delay([tail_rows[1]], baseline_width_px=flow_fit["steady_width_baseline_px"]),
    ]
    refine_summaries = [
        online_tail_mod.summarize_online_stream_tail_delay([tail_rows[2]], baseline_width_px=flow_fit["steady_width_baseline_px"]),
    ]
    tail_result = online_tail_mod.resolve_online_stream_tail_result(
        flow_fit_result=flow_fit,
        tail_plan=tail_plan,
        coarse_summaries=coarse_summaries,
        refine_summaries=refine_summaries,
        trigger_bracket={
            "tail_phase_status": "captured",
            "termination_reason": "refine_trigger",
            "trigger_delay_us": 7200,
            "last_nontrigger_delay_us": 7000,
            "trigger_reason": "refine_width_frac_le_0.95",
            "warnings": [],
        },
    )

    _write_json(
        run_dir / "plan_snapshot.json",
        online_cal_mod.build_online_stream_plan_snapshot(
            condition=condition,
            priors=priors,
            flow_plan=flow_plan,
            tail_plan=tail_plan,
            capture_budget=online_cal_mod.new_online_stream_budget(),
            analysis_config=online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG,
        ),
    )
    _write_json(
        run_dir / "prior_resolution.json",
        online_cal_mod.build_online_stream_prior_resolution_artifact(
            condition=condition,
            lookup={"looked_up": True, "candidate_found": True},
            candidate_prior={"source": "calibration_memory", "flow_start_offset_us": 650, "tail_start_offset_us": 3950},
            applied_prior={"source": "calibration_memory", "flow_start_offset_us": 650, "tail_start_offset_us": 3950},
            fallback_reason=None,
            warnings=[],
        ),
    )
    _write_json(
        run_dir / "flow_fit.json",
        online_cal_mod.build_online_stream_flow_fit_artifact(
            condition=condition,
            flow_plan=flow_plan,
            accepted_delay_points=flow_fit.get("accepted_delay_points"),
            fit=flow_fit,
            warnings=flow_fit.get("warnings"),
        ),
    )
    _write_json(
        run_dir / "tail_fit.json",
        online_tail_mod.build_online_stream_tail_fit_artifact(
            condition=condition,
            tail_plan=tail_plan,
            steady_width_baseline_px=flow_fit.get("steady_width_baseline_px"),
            coarse_delay_summaries=coarse_summaries,
            refine_delay_summaries=refine_summaries,
            result=tail_result,
            warnings=tail_result.get("warnings"),
        ),
    )
    _write_jsonl(run_dir / "frames.jsonl", flow_rows + tail_rows)
    return tail_result


def test_replay_online_stream_run_matches_stored_artifacts(tmp_path):
    run_dir = tmp_path / "run_01"
    _build_consistent_run(run_dir)

    report = online_replay_mod.replay_online_stream_run(run_dir)

    assert report["artifacts_present"]["flow_fit"] is True
    assert report["artifacts_present"]["tail_fit"] is True
    assert report["comparison"]["all_match"] is True
    assert report["comparison"]["tail_start_delay_from_emergence_us"]["matches"] is True


def test_replay_online_stream_run_reports_mismatches_for_tampered_artifact(tmp_path):
    run_dir = tmp_path / "run_01"
    _build_consistent_run(run_dir)

    tail_fit_path = run_dir / "tail_fit.json"
    tail_fit = json.loads(tail_fit_path.read_text(encoding="utf-8"))
    tail_fit["result"]["predicted_volume_nl"] = 999.0
    tail_fit_path.write_text(json.dumps(tail_fit, indent=2), encoding="utf-8")

    report = online_replay_mod.replay_online_stream_run(run_dir)

    assert report["comparison"]["all_match"] is False
    assert report["comparison"]["predicted_volume_nl"]["matches"] is False


def test_replay_accepted_measurements_include_qc_and_clearance_fields():
    frame_rows = [
        online_cal_mod.build_online_stream_frame_row(
            phase="flow_rate",
            status="accepted",
            delay_us=3850,
            delay_from_emergence_us=650,
            replicate_index=1,
            qc={
                "measurement_qc_pass": True,
                "nozzle_qc_pass": True,
                "silhouette_qc_pass": True,
            },
            image_ref={"capture_id": "flow_01"},
            warnings=[],
            attached_width_px=74.5,
            visible_volume_nl=12.0,
            attached_bottom_clearance_px=180,
        )
    ]

    measurements = online_replay_mod._accepted_measurements(frame_rows, phases=("flow_rate",))

    assert len(measurements) == 1
    assert measurements[0]["nozzle_qc_pass"] is True
    assert measurements[0]["silhouette_qc_pass"] is True
    assert measurements[0]["attached_bottom_clearance_px"] == 180.0


def test_replay_accepted_measurements_tolerate_legacy_rows_without_new_fields():
    frame_rows = [
        {
            "phase": "flow_rate",
            "status": "accepted",
            "delay_us": 3850,
            "delay_from_emergence_us": 650,
            "replicate_index": 1,
            "attached_width_px": 74.5,
            "visible_volume_nl": 12.0,
            "image_ref": {"capture_id": "legacy_flow_01"},
        }
    ]

    measurements = online_replay_mod._accepted_measurements(frame_rows, phases=("flow_rate",))

    assert len(measurements) == 1
    assert measurements[0]["nozzle_qc_pass"] is None
    assert measurements[0]["silhouette_qc_pass"] is None
    assert measurements[0]["attached_bottom_clearance_px"] is None
