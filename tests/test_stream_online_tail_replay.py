from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import online_fit as online_fit_mod
from tools.stream_analysis import online_tail as online_tail_mod


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = (
    REPO_ROOT
    / "FreeRTOS-interface"
    / "Experiments"
    / "Stream_characterization-20260327_225650"
)
SUMMARY_CSV = EXPERIMENT_ROOT / "analysis" / "stream_characterization" / "experiment_summary.csv"


def _read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _to_int(value):
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _feature_row_is_flow_accepted(row: dict) -> bool:
    return bool(
        str(row.get("silhouette_status") or "") == "ok"
        and _to_float(row.get("attached_near_nozzle_width_median_px")) is not None
        and _to_float(row.get("total_visible_volume_nl")) is not None
        and (_to_float(row.get("min_accepted_fluid_distance_from_bottom_px")) or 0.0) > 96.0
    )


def _feature_row_is_tail_width_usable(row: dict) -> bool:
    return bool(
        str(row.get("silhouette_status") or "") == "ok"
        and _to_float(row.get("attached_near_nozzle_width_median_px")) is not None
    )


def _feature_row_is_tail_landmark(row: dict) -> bool:
    cutoff_y_px = _to_float(row.get("cutoff_y_px"))
    selected_component_top_y_px = _to_float(row.get("selected_component_top_y_px"))
    near_nozzle_band_top_px = float(
        online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG["near_nozzle_band_top_px"]
    )
    if cutoff_y_px is None or selected_component_top_y_px is None:
        return False
    return bool(selected_component_top_y_px > (cutoff_y_px + near_nozzle_band_top_px))


def _phase_features_by_delay(run_id: str) -> dict[int, dict]:
    phase_features_path = (
        EXPERIMENT_ROOT
        / "analysis"
        / "stream_characterization"
        / "runs"
        / run_id
        / "stage_05_fit"
        / "phase_features.csv"
    )
    if not phase_features_path.exists():
        return {}
    rows = {}
    for row in _read_csv_rows(phase_features_path):
        delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if delay_from_emergence_us is None:
            continue
        rows[int(delay_from_emergence_us)] = row
    return rows


def _build_sparse_flow_fit(rows_by_delay: dict[int, dict]):
    schedule_offsets_us = online_cal_mod.build_online_stream_flow_plan(
        emergence_time_us=0
    )["delay_offsets_from_emergence_us"]
    measurements = []
    delay_summaries = []
    for offset_us in list(schedule_offsets_us):
        feature_row = rows_by_delay.get(int(offset_us))
        if feature_row is None:
            continue
        delay_us = _to_int(feature_row.get("flash_delay_us"))
        if delay_us is None:
            continue
        capture_id = str(feature_row.get("capture_id") or f"replay_{offset_us}")
        if _feature_row_is_flow_accepted(feature_row):
            frame_rows = [
                online_cal_mod.build_online_stream_frame_row(
                    phase="flow_rate",
                    status="accepted",
                    delay_us=delay_us,
                    delay_from_emergence_us=int(offset_us),
                    replicate_index=1,
                    qc={"measurement_qc_pass": True},
                    image_ref={"capture_id": capture_id},
                    warnings=[],
                    attached_width_px=_to_float(feature_row.get("attached_near_nozzle_width_median_px")),
                    visible_volume_nl=_to_float(feature_row.get("total_visible_volume_nl")),
                    attached_bottom_clearance_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    min_accepted_fluid_distance_from_bottom_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    accepted_component_count=_to_int(feature_row.get("accepted_component_count")) or 0,
                    accepted_detached_component_count=_to_int(
                        feature_row.get("accepted_detached_component_count")
                    )
                    or 0,
                    detached_near_bottom_warning=False,
                    attached_bottom_guard_hit=False,
                )
            ]
            measurements.append(
                online_cal_mod.build_online_stream_measurement_row(
                    phase="flow_rate",
                    delay_us=delay_us,
                    delay_from_emergence_us=int(offset_us),
                    replicate_index=1,
                    width_px=_to_float(feature_row.get("attached_near_nozzle_width_median_px")),
                    visible_volume_nl=_to_float(feature_row.get("total_visible_volume_nl")),
                    qc_pass=True,
                    image_ref={"capture_id": capture_id},
                )
            )
        else:
            frame_rows = [
                online_cal_mod.build_online_stream_frame_row(
                    phase="flow_rate",
                    status="rejected_replay_qc",
                    delay_us=delay_us,
                    delay_from_emergence_us=int(offset_us),
                    replicate_index=1,
                    qc={"measurement_qc_pass": False},
                    image_ref={"capture_id": capture_id},
                    warnings=["replay_qc_failed"],
                    attached_width_px=_to_float(feature_row.get("attached_near_nozzle_width_median_px")),
                    visible_volume_nl=_to_float(feature_row.get("total_visible_volume_nl")),
                    attached_bottom_clearance_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    min_accepted_fluid_distance_from_bottom_px=_to_float(
                        feature_row.get("min_accepted_fluid_distance_from_bottom_px")
                    ),
                    accepted_component_count=_to_int(feature_row.get("accepted_component_count")) or 0,
                    accepted_detached_component_count=_to_int(
                        feature_row.get("accepted_detached_component_count")
                    )
                    or 0,
                    detached_near_bottom_warning=False,
                    attached_bottom_guard_hit=False,
                )
            ]
        delay_summaries.append(online_cal_mod.summarize_online_stream_flow_delay(frame_rows))

    fit_result = online_fit_mod.fit_online_stream_flow_phase(
        measurements=measurements,
        delay_summaries=delay_summaries,
    )
    if (
        str(fit_result.get("fit_status") or "").startswith("unresolved")
        and fit_result.get("steady_width_baseline_px") is not None
        and len(measurements) >= 2
    ):
        x_values = [float(row["delay_from_emergence_us"]) for row in measurements]
        y_values = [float(row["visible_volume_nl"]) for row in measurements]
        x_mean = sum(x_values) / float(len(x_values))
        y_mean = sum(y_values) / float(len(y_values))
        denom = sum((value - x_mean) ** 2 for value in x_values)
        if denom > 0.0:
            slope = sum(
                (x_value - x_mean) * (y_value - y_mean)
                for x_value, y_value in zip(x_values, y_values)
            ) / denom
            intercept = y_mean - (slope * x_mean)
            fit_result = {
                **dict(fit_result or {}),
                "fit_status": "warning_sparse_replay_fallback_fit",
                "flow_rate_nl_per_us": float(slope),
                "flow_intercept_nl": float(intercept),
                "flow_fit_delay_start_from_emergence_us": int(min(x_values)),
                "flow_fit_delay_end_from_emergence_us": int(max(x_values)),
                "flow_fit_point_count": int(len(x_values)),
                "warnings": list(dict(fit_result or {}).get("warnings") or [])
                + ["sparse_replay_flow_fit_fallback"],
            }
    return fit_result, delay_summaries


def _build_tail_delay_summary(
    rows_by_delay: dict[int, dict],
    *,
    delay_from_emergence_us: int,
    baseline_width_px: float,
    phase: str,
):
    feature_row = rows_by_delay.get(int(delay_from_emergence_us))
    if feature_row is None:
        return online_tail_mod.summarize_online_stream_tail_delay(
            [
                {
                    "phase": phase,
                    "status": "rejected_replay_missing",
                    "delay_us": int(delay_from_emergence_us),
                    "delay_from_emergence_us": int(delay_from_emergence_us),
                    "replicate_index": 1,
                    "qc": {"tail_qc_pass": False, "tail_width_usable": False, "tail_landmark_usable": False},
                    "image_ref": {"capture_id": f"missing_{delay_from_emergence_us}"},
                    "warnings": ["replay_row_missing"],
                    "attached_width_px": None,
                    "tail_width_usable": False,
                    "tail_landmark_usable": False,
                    "separated_from_nozzle_landmark": False,
                }
            ],
            baseline_width_px=baseline_width_px,
        )

    delay_us = _to_int(feature_row.get("flash_delay_us")) or int(delay_from_emergence_us)
    capture_id = str(feature_row.get("capture_id") or f"tail_{delay_from_emergence_us}")
    width_usable = _feature_row_is_tail_width_usable(feature_row)
    separated_landmark = _feature_row_is_tail_landmark(feature_row)
    status = "accepted" if (width_usable or separated_landmark) else "rejected_replay_qc"
    frame_rows = [
        {
            "phase": phase,
            "status": status,
            "delay_us": int(delay_us),
            "delay_from_emergence_us": int(delay_from_emergence_us),
            "replicate_index": 1,
            "qc": {
                "tail_qc_pass": bool(width_usable),
                "tail_width_usable": bool(width_usable),
                "tail_landmark_usable": bool(separated_landmark),
            },
            "image_ref": {"capture_id": capture_id},
            "warnings": [] if status == "accepted" else ["replay_tail_qc_failed"],
            "attached_width_px": _to_float(feature_row.get("attached_near_nozzle_width_median_px")),
            "tail_width_usable": bool(width_usable),
            "tail_landmark_usable": bool(separated_landmark),
            "separated_from_nozzle_landmark": bool(separated_landmark),
            "attached_bottom_guard_hit": False,
            "detached_near_bottom_warning": False,
            "late_frame_warning": False,
        }
    ]
    return online_tail_mod.summarize_online_stream_tail_delay(
        frame_rows,
        baseline_width_px=baseline_width_px,
    )


def _replay_tail_result(rows_by_delay: dict[int, dict]):
    flow_fit_result, flow_delay_summaries = _build_sparse_flow_fit(rows_by_delay)
    capture_budget = online_cal_mod.consume_online_stream_budget(
        online_cal_mod.new_online_stream_budget(),
        phase="flow_phase",
        count=15,
    )
    tail_plan = online_tail_mod.plan_online_stream_tail_phase(
        flow_fit_result=flow_fit_result,
        priors=None,
        emergence_time_us=0,
        capture_budget=capture_budget,
        flow_delay_summaries=flow_delay_summaries,
        policy={"scout_replicates": 1, "backtrack_replicates": 1},
    )
    if not tail_plan["run_tail"]:
        return online_tail_mod.resolve_online_stream_tail_result(
            flow_fit_result=flow_fit_result,
            tail_plan=tail_plan,
            scout_summaries=[],
            backtrack_summaries=[],
            trigger_bracket={
                "tail_phase_status": "unresolved_missing_flow_baseline",
                "termination_reason": "missing_flow_baseline",
                "warnings": ["unresolved_missing_flow_baseline"],
            },
            flow_delay_summaries=flow_delay_summaries,
        )

    baseline_width_px = float(tail_plan["steady_width_baseline_px"])
    scout_summaries = []
    landmark_delay_us = None
    landmark_reason = None
    backtrack_left_delay_us = None
    scout_delays = [
        int(tail_plan["scout_first_delay_us"] + (idx * tail_plan["scout_step_us"]))
        for idx in range(int(tail_plan["planned_scout_delay_count"]))
    ]

    for scout_index, scout_delay_us in enumerate(scout_delays):
        summary = _build_tail_delay_summary(
            rows_by_delay,
            delay_from_emergence_us=int(scout_delay_us),
            baseline_width_px=baseline_width_px,
            phase="tail_scout",
        )
        scout_summaries.append(summary)
        if bool(summary.get("delay_accepted")) and bool(summary.get("landmark_detected")):
            landmark_delay_us = int(summary["delay_us"])
            landmark_reason = str(summary.get("landmark_reason") or "")
            if scout_index > 0:
                backtrack_left_delay_us = int(scout_delays[scout_index - 1])
            else:
                backtrack_left_delay_us = int(tail_plan["scout_anchor_delay_us"])
            break

    if landmark_delay_us is None:
        return online_tail_mod.resolve_online_stream_tail_result(
            flow_fit_result=flow_fit_result,
            tail_plan=tail_plan,
            scout_summaries=scout_summaries,
            backtrack_summaries=[],
            trigger_bracket={
                "tail_phase_status": "unresolved_no_landmark",
                "termination_reason": "no_scout_landmark",
                "warnings": ["unresolved_no_landmark"],
            },
            flow_delay_summaries=flow_delay_summaries,
        )

    backtrack_summaries = []
    for backtrack_delay_us in online_tail_mod.build_online_stream_tail_backtrack_plan(
        left_endpoint_delay_us=backtrack_left_delay_us,
        landmark_delay_us=landmark_delay_us,
        backtrack_step_us=int(tail_plan["backtrack_step_us"]),
    ):
        backtrack_summaries.append(
            _build_tail_delay_summary(
                rows_by_delay,
                delay_from_emergence_us=int(backtrack_delay_us),
                baseline_width_px=baseline_width_px,
                phase="tail_backtrack",
            )
        )

    return online_tail_mod.resolve_online_stream_tail_result(
        flow_fit_result=flow_fit_result,
        tail_plan=tail_plan,
        scout_summaries=scout_summaries,
        backtrack_summaries=backtrack_summaries,
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": landmark_delay_us,
            "backtrack_left_delay_us": backtrack_left_delay_us,
            "landmark_reason": landmark_reason,
        },
        flow_delay_summaries=flow_delay_summaries,
    )


def test_sparse_online_tail_replay_ignores_bottom_of_fov_signals_without_landmark():
    rows_by_delay = {
        650: {
            "flash_delay_us": 650,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 74.0,
            "total_visible_volume_nl": 12.0,
            "min_accepted_fluid_distance_from_bottom_px": 180.0,
        },
        850: {
            "flash_delay_us": 850,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 74.0,
            "total_visible_volume_nl": 15.0,
            "min_accepted_fluid_distance_from_bottom_px": 170.0,
        },
        1050: {
            "flash_delay_us": 1050,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.8,
            "total_visible_volume_nl": 18.5,
            "min_accepted_fluid_distance_from_bottom_px": 160.0,
        },
        1550: {
            "flash_delay_us": 1550,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.7,
            "total_visible_volume_nl": 20.0,
            "min_accepted_fluid_distance_from_bottom_px": 40.0,
            "selected_component_top_y_px": 80.0,
            "cutoff_y_px": 70.0,
        },
    }

    result = _replay_tail_result(rows_by_delay)

    assert result["tail_phase"]["status"] == "unresolved_no_landmark"


def test_sparse_online_tail_replay_matches_dense_offline_tail_start_with_scout_backtrack():
    if not SUMMARY_CSV.exists():
        pytest.skip("Archived stream-analysis experiment summary is not available.")

    errors = []
    for row in _read_csv_rows(SUMMARY_CSV):
        if str(row.get("analysis_source_mode") or "") != "raw":
            continue
        if str(row.get("steady_fit_status") or "") != "ok":
            continue
        if str(row.get("tail_onset_status") or "") != "ok":
            continue
        run_id = str(row.get("run_id") or "").strip()
        gold_tail_start_delay_us = _to_int(row.get("tail_start_delay_from_emergence_us"))
        if not run_id or gold_tail_start_delay_us is None:
            continue
        rows_by_delay = _phase_features_by_delay(run_id)
        if not rows_by_delay:
            continue
        result = _replay_tail_result(rows_by_delay)
        if str(result.get("tail_phase", {}).get("status") or "") not in {"captured", "advisory_landmark_only"}:
            continue
        predicted_tail_start_delay_us = _to_int(
            result.get("tail_phase", {}).get("tail_start_delay_from_emergence_us")
        )
        if predicted_tail_start_delay_us is None:
            continue
        errors.append(abs(int(predicted_tail_start_delay_us) - int(gold_tail_start_delay_us)))

    if len(errors) < 5:
        pytest.skip("Archived dense replay set does not yield enough resolved scout/backtrack tail results.")
    sorted_errors = sorted(int(value) for value in errors)
    median_error = sorted_errors[len(sorted_errors) // 2]
    worst_error = max(sorted_errors)

    assert median_error <= 400
    assert worst_error <= 700
