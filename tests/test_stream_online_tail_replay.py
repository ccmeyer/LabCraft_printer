from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from tools.stream_analysis import online_fit as online_fit_mod
from tools.stream_analysis import online_tail as online_tail_mod
from tests.stream_online_replay_helpers import build_adaptive_flow_replay_inputs
from tests.stream_online_replay_helpers import to_float as _to_float
from tests.stream_online_replay_helpers import to_int as _to_int
from tools.stream_analysis import online_calibration as online_cal_mod


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = (
    REPO_ROOT
    / "FreeRTOS-interface"
    / "Experiments"
    / "Stream_characterization-20260327_225650"
)
SUMMARY_CSV = EXPERIMENT_ROOT / "analysis" / "stream_characterization" / "experiment_summary.csv"
HTPS_ONLINE_STREAM_ROOT = (
    REPO_ROOT
    / "FreeRTOS-interface"
    / "Experiments"
    / "HTPS_rep1-20260423_200444"
    / "calibration_recordings"
    / "OnlineStreamCalibrationProcess"
)


def _read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return dict(json.load(handle) or {})


def _delay_us_for_offset(rows: list[dict], delay_from_emergence_us: int | None) -> int | None:
    offset = _to_int(delay_from_emergence_us)
    if offset is None:
        return None
    for row in list(rows or []):
        if _to_int(dict(row or {}).get("delay_from_emergence_us")) == int(offset):
            return _to_int(dict(row or {}).get("delay_us"))
    return None


def _first_int(*values):
    for value in values:
        parsed = _to_int(value)
        if parsed is not None:
            return int(parsed)
    return None


def _resolve_htps_tail_artifact(run_id: str) -> dict:
    run_dir = HTPS_ONLINE_STREAM_ROOT / run_id
    if not (run_dir / "tail_fit.json").exists():
        pytest.skip(f"missing HTPS tail artifact: {run_id}")
    tail_artifact = _read_json(run_dir / "tail_fit.json")
    flow_artifact = _read_json(run_dir / "flow_fit.json")
    tail_phase = dict((dict(tail_artifact.get("result") or {}).get("tail_phase") or {}))
    scout_summaries = [dict(row or {}) for row in list(tail_artifact.get("scout_delay_summaries") or [])]
    backtrack_summaries = [dict(row or {}) for row in list(tail_artifact.get("backtrack_delay_summaries") or [])]
    flow_delay_summaries = [dict(row or {}) for row in list(flow_artifact.get("delay_summaries") or [])]
    all_rows = list(scout_summaries) + list(backtrack_summaries) + list(flow_delay_summaries)
    landmark_delay_us = _delay_us_for_offset(
        all_rows,
        _first_int(
            tail_phase.get("landmark_delay_from_emergence_us"),
            tail_phase.get("trigger_delay_from_emergence_us"),
        ),
    )
    backtrack_left_delay_us = _delay_us_for_offset(
        all_rows,
        _first_int(
            tail_phase.get("last_nontrigger_delay_from_emergence_us"),
            tail_phase.get("last_plateau_delay_from_emergence_us"),
        ),
    )
    analysis_config = dict((tail_phase.get("analysis_config") or {}))
    analysis_config["segmented_tail_online_controlling_enabled"] = False
    return online_tail_mod.resolve_online_stream_tail_result(
        flow_fit_result=dict(flow_artifact.get("fit") or flow_artifact.get("result") or {}),
        tail_plan=dict(tail_artifact.get("tail_plan") or {}),
        scout_summaries=scout_summaries,
        backtrack_summaries=backtrack_summaries,
        trigger_bracket={
            "tail_phase_status": "",
            "termination_reason": "",
            "landmark_delay_us": landmark_delay_us,
            "backtrack_left_delay_us": backtrack_left_delay_us,
            "landmark_reason": str(tail_phase.get("landmark_reason") or tail_phase.get("trigger_reason") or ""),
            "warnings": list(tail_phase.get("warnings") or []),
        },
        flow_delay_summaries=flow_delay_summaries,
        analysis_config=analysis_config,
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
    measurements, delay_summaries = build_adaptive_flow_replay_inputs(
        rows_by_delay,
        fit_module=online_fit_mod,
        capture_id_prefix="replay",
    )

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
    flow_capture_count = int(len(flow_delay_summaries))
    capture_budget = online_cal_mod.consume_online_stream_budget(
        online_cal_mod.new_online_stream_budget(),
        phase="flow_phase",
        count=int(flow_capture_count),
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
            analysis_config={"segmented_tail_online_controlling_enabled": False},
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
            analysis_config={"segmented_tail_online_controlling_enabled": False},
        )

    backtrack_summaries = []
    for backtrack_delay_us in online_tail_mod.build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=int(tail_plan["scout_anchor_delay_us"]),
        left_endpoint_delay_us=backtrack_left_delay_us,
        landmark_delay_us=landmark_delay_us,
        backtrack_step_us=int(tail_plan["backtrack_step_us"]),
        fine_prepad_us=int(tail_plan.get("fine_prepad_us") or 100),
        fine_postpad_us=int(tail_plan.get("fine_postpad_us") or 100),
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
        analysis_config={"segmented_tail_online_controlling_enabled": False},
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
        700: {
            "flash_delay_us": 700,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 74.0,
            "total_visible_volume_nl": 12.8,
            "min_accepted_fluid_distance_from_bottom_px": 178.0,
        },
        750: {
            "flash_delay_us": 750,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 74.0,
            "total_visible_volume_nl": 13.6,
            "min_accepted_fluid_distance_from_bottom_px": 176.0,
        },
        800: {
            "flash_delay_us": 800,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 74.0,
            "total_visible_volume_nl": 14.4,
            "min_accepted_fluid_distance_from_bottom_px": 174.0,
        },
        850: {
            "flash_delay_us": 850,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 74.0,
            "total_visible_volume_nl": 15.0,
            "min_accepted_fluid_distance_from_bottom_px": 170.0,
        },
        900: {
            "flash_delay_us": 900,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.9,
            "total_visible_volume_nl": 15.8,
            "min_accepted_fluid_distance_from_bottom_px": 168.0,
        },
        950: {
            "flash_delay_us": 950,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.9,
            "total_visible_volume_nl": 16.6,
            "min_accepted_fluid_distance_from_bottom_px": 166.0,
        },
        1000: {
            "flash_delay_us": 1000,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.8,
            "total_visible_volume_nl": 17.4,
            "min_accepted_fluid_distance_from_bottom_px": 163.0,
        },
        1050: {
            "flash_delay_us": 1050,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.8,
            "total_visible_volume_nl": 18.5,
            "min_accepted_fluid_distance_from_bottom_px": 160.0,
        },
        1100: {
            "flash_delay_us": 1100,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.8,
            "total_visible_volume_nl": 20.0,
            "min_accepted_fluid_distance_from_bottom_px": 158.0,
        },
        1150: {
            "flash_delay_us": 1150,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.7,
            "total_visible_volume_nl": 21.5,
            "min_accepted_fluid_distance_from_bottom_px": 155.0,
        },
        1200: {
            "flash_delay_us": 1200,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.7,
            "total_visible_volume_nl": 22.2,
            "min_accepted_fluid_distance_from_bottom_px": 154.0,
        },
        1250: {
            "flash_delay_us": 1250,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.7,
            "total_visible_volume_nl": 23.0,
            "min_accepted_fluid_distance_from_bottom_px": 152.0,
        },
        1300: {
            "flash_delay_us": 1300,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.6,
            "total_visible_volume_nl": 23.8,
            "min_accepted_fluid_distance_from_bottom_px": 151.5,
        },
        1350: {
            "flash_delay_us": 1350,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.6,
            "total_visible_volume_nl": 24.6,
            "min_accepted_fluid_distance_from_bottom_px": 151.0,
        },
        1400: {
            "flash_delay_us": 1400,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.6,
            "total_visible_volume_nl": 25.4,
            "min_accepted_fluid_distance_from_bottom_px": 150.8,
        },
        1450: {
            "flash_delay_us": 1450,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.6,
            "total_visible_volume_nl": 26.1,
            "min_accepted_fluid_distance_from_bottom_px": 150.5,
        },
        1650: {
            "flash_delay_us": 1650,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.5,
            "total_visible_volume_nl": 29.2,
            "min_accepted_fluid_distance_from_bottom_px": 149.5,
        },
        1750: {
            "flash_delay_us": 1750,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.5,
            "total_visible_volume_nl": 30.7,
            "min_accepted_fluid_distance_from_bottom_px": 148.0,
        },
        1850: {
            "flash_delay_us": 1850,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.4,
            "total_visible_volume_nl": 32.2,
            "min_accepted_fluid_distance_from_bottom_px": 147.0,
        },
        1950: {
            "flash_delay_us": 1950,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.4,
            "total_visible_volume_nl": 33.8,
            "min_accepted_fluid_distance_from_bottom_px": 146.0,
        },
        2050: {
            "flash_delay_us": 2050,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.3,
            "total_visible_volume_nl": 35.3,
            "min_accepted_fluid_distance_from_bottom_px": 145.5,
        },
        2150: {
            "flash_delay_us": 2150,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.3,
            "total_visible_volume_nl": 36.8,
            "min_accepted_fluid_distance_from_bottom_px": 145.0,
        },
        2250: {
            "flash_delay_us": 2250,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 73.2,
            "total_visible_volume_nl": 38.4,
            "min_accepted_fluid_distance_from_bottom_px": 144.0,
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


def test_sparse_online_tail_replay_applies_settling_rule_to_long_separated_shoulder(monkeypatch):
    monkeypatch.setattr(
        sys.modules[__name__],
        "_build_sparse_flow_fit",
        lambda rows_by_delay: (
            {
                "fit_status": "ok",
                "steady_width_baseline_px": 74.0,
                "flow_rate_nl_per_us": 0.02,
                "flow_intercept_nl": 0.0,
            },
            [
                {
                    "delay_us": 650,
                    "delay_from_emergence_us": 650,
                    "attempted_replicates": 1,
                    "accepted_replicates": 1,
                    "rejected_replicates": 0,
                    "median_width_px": 74.0,
                    "delay_accepted": True,
                    "warnings": [],
                },
                {
                    "delay_us": 850,
                    "delay_from_emergence_us": 850,
                    "attempted_replicates": 1,
                    "accepted_replicates": 1,
                    "rejected_replicates": 0,
                    "median_width_px": 74.0,
                    "delay_accepted": True,
                    "warnings": [],
                },
                {
                    "delay_us": 1000,
                    "delay_from_emergence_us": 1000,
                    "attempted_replicates": 1,
                    "accepted_replicates": 1,
                    "rejected_replicates": 0,
                    "median_width_px": 74.0,
                    "delay_accepted": True,
                    "warnings": [],
                },
            ],
        ),
    )

    rows_by_delay = {
        1000: {
            "flash_delay_us": 1000,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 74.1,
            "total_visible_volume_nl": 19.0,
            "min_accepted_fluid_distance_from_bottom_px": 166.0,
        },
        1050: {
            "flash_delay_us": 1050,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 71.5,
            "total_visible_volume_nl": 20.1,
            "min_accepted_fluid_distance_from_bottom_px": 164.0,
        },
        1100: {
            "flash_delay_us": 1100,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 72.8,
            "total_visible_volume_nl": 21.2,
            "min_accepted_fluid_distance_from_bottom_px": 162.0,
        },
        1150: {
            "flash_delay_us": 1150,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 70.0,
            "total_visible_volume_nl": 22.3,
            "min_accepted_fluid_distance_from_bottom_px": 160.0,
        },
        1200: {
            "flash_delay_us": 1200,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 69.5,
            "total_visible_volume_nl": 23.3,
            "min_accepted_fluid_distance_from_bottom_px": 158.0,
        },
        1250: {
            "flash_delay_us": 1250,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 69.0,
            "total_visible_volume_nl": 24.2,
            "min_accepted_fluid_distance_from_bottom_px": 156.0,
        },
        1300: {
            "flash_delay_us": 1300,
            "silhouette_status": "ok",
            "attached_near_nozzle_width_median_px": 68.5,
            "total_visible_volume_nl": 25.0,
            "min_accepted_fluid_distance_from_bottom_px": 154.0,
        },
        1500: {
            "flash_delay_us": 1500,
            "silhouette_status": "rejected_qc",
            "attached_near_nozzle_width_median_px": None,
            "total_visible_volume_nl": 27.0,
            "min_accepted_fluid_distance_from_bottom_px": 152.0,
            "selected_component_top_y_px": 110.0,
            "cutoff_y_px": 70.0,
        },
    }

    result = _replay_tail_result(rows_by_delay)

    assert result["tail_phase"]["status"] == "captured"
    assert result["tail_phase"]["tail_settling_rule_applied"] is True
    assert result["tail_phase"]["tail_start_selection_method"] == online_tail_mod.TAIL_SETTLING_SELECTION_METHOD
    assert result["tail_phase"]["initial_confirmed_collapse_delay_from_emergence_us"] == 1150
    assert result["tail_phase"]["tail_start_delay_from_emergence_us"] == 1150
    assert result["tail_phase"]["confirmed_collapse_delay_from_emergence_us"] == 1150


@pytest.mark.parametrize(
    ("run_id", "prior_tail_start_us"),
    [
        ("run_20260423_200714_f6304546", 3900),
        ("run_20260423_200738_6aa1a40c", 3900),
        ("run_20260423_201547_0ba2972f", 3950),
    ],
)
def test_htps_tail_replay_keeps_normal_runs_near_prior_behavior(run_id, prior_tail_start_us):
    result = _resolve_htps_tail_artifact(run_id)
    tail_phase = result["tail_phase"]

    assert tail_phase["status"] == "captured"
    assert abs(int(tail_phase["tail_start_delay_from_emergence_us"]) - int(prior_tail_start_us)) <= 100


@pytest.mark.parametrize(
    ("run_id", "minimum_tail_start_us"),
    [
        ("run_20260423_203233_f91d1fd4", 3900),
        ("run_20260423_202911_963b0643", 3900),
        ("run_20260423_200802_1b56cac7", 3950),
        ("run_20260423_201613_152ceb5c", 3900),
    ],
)
def test_htps_tail_replay_moves_early_selection_runs_later(run_id, minimum_tail_start_us):
    result = _resolve_htps_tail_artifact(run_id)
    tail_phase = result["tail_phase"]

    assert tail_phase["status"] == "captured"
    assert int(tail_phase["tail_start_delay_from_emergence_us"]) >= int(minimum_tail_start_us)


def test_htps_tail_replay_flags_right_extension_for_incomplete_window_run():
    result = _resolve_htps_tail_artifact("run_20260423_203233_f91d1fd4")
    tail_phase = result["tail_phase"]

    assert tail_phase["tail_right_extension_needed"] is True
    assert tail_phase["tail_min_width_at_right_edge"] is True
    assert tail_phase["tail_width_still_falling_at_right_edge"] is True


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
