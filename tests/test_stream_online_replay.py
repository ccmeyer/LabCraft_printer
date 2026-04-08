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
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _condition():
    return {
        "print_pressure_psi": 1.61,
        "print_pulse_width_us": 1500,
        "emergence_time_us": 3200,
        "stock_solution": "Water",
        "printer_head_id": "PH-001",
    }


def _prior_resolution(condition: dict):
    return online_cal_mod.build_online_stream_prior_resolution_artifact(
        condition=condition,
        lookup={"looked_up": False, "candidate_found": False},
        candidate_prior={},
        applied_prior={"source": "default"},
        fallback_reason="no_prior",
        warnings=[],
    )


def _build_flow_rows():
    return [
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


def _build_tail_rows(*, scout_phase: str, backtrack_phase: str):
    return [
        online_cal_mod.build_online_stream_frame_row(
            phase=scout_phase,
            status="accepted",
            delay_us=4750,
            delay_from_emergence_us=1550,
            replicate_index=1,
            qc={"tail_qc_pass": False, "tail_width_usable": False, "tail_landmark_usable": True},
            image_ref={"capture_id": "tail_s_01"},
            warnings=[],
            attached_width_px=None,
            tail_width_usable=False,
            tail_landmark_usable=True,
            separated_from_nozzle_landmark=True,
            landmark_reason="separated_from_nozzle",
        ),
        online_cal_mod.build_online_stream_frame_row(
            phase=backtrack_phase,
            status="accepted",
            delay_us=4300,
            delay_from_emergence_us=1100,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "tail_b_01"},
            warnings=[],
            attached_width_px=74.1,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        ),
        online_cal_mod.build_online_stream_frame_row(
            phase=backtrack_phase,
            status="accepted",
            delay_us=4350,
            delay_from_emergence_us=1150,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "tail_b_02"},
            warnings=[],
            attached_width_px=73.9,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        ),
        online_cal_mod.build_online_stream_frame_row(
            phase=backtrack_phase,
            status="accepted",
            delay_us=4400,
            delay_from_emergence_us=1200,
            replicate_index=1,
            qc={"tail_qc_pass": True, "tail_width_usable": True, "tail_landmark_usable": False},
            image_ref={"capture_id": "tail_b_03"},
            warnings=[],
            attached_width_px=73.0,
            tail_width_usable=True,
            tail_landmark_usable=False,
            separated_from_nozzle_landmark=False,
        ),
    ]


def _build_run(run_dir: Path, *, scout_phase: str = "tail_scout", backtrack_phase: str = "tail_backtrack"):
    run_dir.mkdir(parents=True, exist_ok=True)
    condition = _condition()
    prior_resolution = _prior_resolution(condition)
    flow_plan = {
        "emergence_time_us": 3200,
        "delay_offsets_from_emergence_us": [650, 850, 1050],
        "delays_us": [3850, 4050, 4250],
        "replicates_per_delay": 1,
        "point_count": 3,
        "plan_source": "prior_adjusted",
    }
    flow_rows = _build_flow_rows()
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
    flow_delay_summaries = [online_cal_mod.summarize_online_stream_flow_delay([row]) for row in flow_rows]
    flow_fit = online_fit_mod.fit_online_stream_flow_phase(
        measurements=flow_measurements,
        delay_summaries=flow_delay_summaries,
    )
    tail_plan = online_tail_mod.plan_online_stream_tail_phase(
        flow_fit_result=flow_fit,
        priors={"condition_match": "none"},
        emergence_time_us=3200,
        capture_budget={"captures_remaining_hard": 12},
        flow_delay_summaries=flow_delay_summaries,
    )
    tail_plan["planned_scout_delay_count"] = 1
    tail_plan["planned_coarse_delay_count"] = 1
    tail_rows = _build_tail_rows(scout_phase=scout_phase, backtrack_phase=backtrack_phase)
    scout_summaries = [
        online_tail_mod.summarize_online_stream_tail_delay([tail_rows[0]], baseline_width_px=flow_fit["steady_width_baseline_px"])
    ]
    backtrack_summaries = [
        online_tail_mod.summarize_online_stream_tail_delay([tail_rows[1]], baseline_width_px=flow_fit["steady_width_baseline_px"]),
        online_tail_mod.summarize_online_stream_tail_delay([tail_rows[2]], baseline_width_px=flow_fit["steady_width_baseline_px"]),
        online_tail_mod.summarize_online_stream_tail_delay([tail_rows[3]], baseline_width_px=flow_fit["steady_width_baseline_px"]),
    ]
    tail_result = online_tail_mod.resolve_online_stream_tail_result(
        flow_fit_result=flow_fit,
        tail_plan=tail_plan,
        scout_summaries=scout_summaries,
        backtrack_summaries=backtrack_summaries,
        flow_delay_summaries=flow_delay_summaries,
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": 4750,
            "backtrack_left_delay_us": 4250,
            "landmark_reason": "separated_from_nozzle",
            "warnings": [],
        },
    )

    _write_json(
        run_dir / "plan_snapshot.json",
        online_cal_mod.build_online_stream_plan_snapshot(
            condition=condition,
            priors=prior_resolution,
            flow_plan=flow_plan,
            tail_plan=tail_plan,
            capture_budget=online_cal_mod.new_online_stream_budget(),
            analysis_config=online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG,
        ),
    )
    _write_json(run_dir / "prior_resolution.json", prior_resolution)
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
            scout_delay_summaries=scout_summaries,
            backtrack_delay_summaries=backtrack_summaries,
            result=tail_result,
            warnings=tail_result.get("warnings"),
        ),
    )
    _write_jsonl(run_dir / "frames.jsonl", flow_rows + tail_rows)


def test_replay_online_stream_run_matches_stored_scout_backtrack_artifacts(tmp_path):
    run_dir = tmp_path / "run_01"
    _build_run(run_dir)

    report = online_replay_mod.replay_online_stream_run(run_dir)

    assert report["artifacts_present"]["flow_fit"] is True
    assert report["artifacts_present"]["tail_fit"] is True
    assert report["comparison"]["all_match"] is True
    assert report["comparison"]["tail_search_method"]["matches"] is True


def test_replay_online_stream_run_accepts_legacy_tail_phase_labels(tmp_path):
    run_dir = tmp_path / "run_01"
    _build_run(run_dir, scout_phase="tail_coarse", backtrack_phase="tail_refine")

    report = online_replay_mod.replay_online_stream_run(run_dir)

    assert report["comparison"]["all_match"] is True
    assert report["replayed"]["tail_result"]["tail_phase"]["status"] == "captured"
    assert report["replayed"]["tail_result"]["tail_phase"]["search_method"] == "separation_landmark_backtrack_v1"


def test_replay_online_stream_run_reports_mismatches_for_tampered_tail_volume(tmp_path):
    run_dir = tmp_path / "run_01"
    _build_run(run_dir)

    tail_fit_path = run_dir / "tail_fit.json"
    tail_fit = json.loads(tail_fit_path.read_text(encoding="utf-8"))
    tail_fit["result"]["predicted_volume_nl"] = 999.0
    tail_fit_path.write_text(json.dumps(tail_fit, indent=2), encoding="utf-8")

    report = online_replay_mod.replay_online_stream_run(run_dir)

    assert report["comparison"]["all_match"] is False
    assert report["comparison"]["predicted_volume_nl"]["matches"] is False


def test_replay_online_stream_run_reports_mismatch_for_tampered_landmark_reason(tmp_path):
    run_dir = tmp_path / "run_01"
    _build_run(run_dir)

    tail_fit_path = run_dir / "tail_fit.json"
    tail_fit = json.loads(tail_fit_path.read_text(encoding="utf-8"))
    tail_fit["result"]["tail_phase"]["landmark_reason"] = "strong_width_collapse_backup"
    tail_fit_path.write_text(json.dumps(tail_fit, indent=2), encoding="utf-8")

    report = online_replay_mod.replay_online_stream_run(run_dir)

    assert report["comparison"]["all_match"] is False
    assert report["comparison"]["tail_trigger_reason"]["matches"] is False
