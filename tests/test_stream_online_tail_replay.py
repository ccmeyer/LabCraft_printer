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


def _feature_row_is_tail_accepted(row: dict) -> bool:
    return bool(
        str(row.get("silhouette_status") or "") == "ok"
        and _to_float(row.get("attached_near_nozzle_width_median_px")) is not None
    )


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
            slope = sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x_values, y_values)) / denom
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
    return fit_result


def _build_tail_delay_summary(rows_by_delay: dict[int, dict], *, delay_from_emergence_us: int, baseline_width_px: float):
    feature_row = rows_by_delay.get(int(delay_from_emergence_us))
    if feature_row is None:
        return online_tail_mod.summarize_online_stream_tail_delay(
            [
                {
                    "phase": "tail_coarse",
                    "status": "rejected_replay_missing",
                    "delay_us": int(delay_from_emergence_us),
                    "delay_from_emergence_us": int(delay_from_emergence_us),
                    "replicate_index": 1,
                    "qc": {"tail_qc_pass": False},
                    "image_ref": {"capture_id": f"missing_{delay_from_emergence_us}"},
                    "warnings": ["replay_row_missing"],
                    "attached_width_px": None,
                }
            ],
            baseline_width_px=baseline_width_px,
        )

    delay_us = _to_int(feature_row.get("flash_delay_us")) or int(delay_from_emergence_us)
    capture_id = str(feature_row.get("capture_id") or f"tail_{delay_from_emergence_us}")
    if _feature_row_is_tail_accepted(feature_row):
        frame_rows = [
            {
                "phase": "tail_coarse",
                "status": "accepted",
                "delay_us": int(delay_us),
                "delay_from_emergence_us": int(delay_from_emergence_us),
                "replicate_index": 1,
                "qc": {"tail_qc_pass": True},
                "image_ref": {"capture_id": capture_id},
                "warnings": [],
                "attached_width_px": _to_float(feature_row.get("attached_near_nozzle_width_median_px")),
            }
        ]
    else:
        frame_rows = [
            {
                "phase": "tail_coarse",
                "status": "rejected_replay_qc",
                "delay_us": int(delay_us),
                "delay_from_emergence_us": int(delay_from_emergence_us),
                "replicate_index": 1,
                "qc": {"tail_qc_pass": False},
                "image_ref": {"capture_id": capture_id},
                "warnings": ["replay_tail_qc_failed"],
                "attached_width_px": _to_float(feature_row.get("attached_near_nozzle_width_median_px")),
            }
        ]
    return online_tail_mod.summarize_online_stream_tail_delay(
        frame_rows,
        baseline_width_px=baseline_width_px,
    )


def _replay_tail_result(rows_by_delay: dict[int, dict]):
    flow_fit_result = _build_sparse_flow_fit(rows_by_delay)
    capture_budget = online_cal_mod.consume_online_stream_budget(
        online_cal_mod.new_online_stream_budget(),
        phase="flow_phase",
        count=15,
    )
    sparse_policy = {
        "coarse_replicates": 1,
        "refine_replicates": 1,
    }
    tail_plan = online_tail_mod.plan_online_stream_tail_phase(
        flow_fit_result=flow_fit_result,
        priors=None,
        emergence_time_us=0,
        capture_budget=capture_budget,
        policy=sparse_policy,
    )
    if not tail_plan["run_tail"]:
        return online_tail_mod.resolve_online_stream_tail_result(
            flow_fit_result=flow_fit_result,
            tail_plan=tail_plan,
            coarse_summaries=[],
            refine_summaries=[],
            trigger_bracket={
                "tail_phase_status": "unresolved_missing_flow_baseline",
                "termination_reason": "missing_flow_baseline",
                "warnings": ["unresolved_missing_flow_baseline"],
            },
        )

    baseline_width_px = float(tail_plan["steady_width_baseline_px"])
    coarse_summaries = []
    refine_summaries = []
    last_nontrigger_delay_us = None
    trigger_delay_us = None
    trigger_reason = None
    capture_budget_state = dict(capture_budget)
    consecutive_failed = 0
    phase_status = "unresolved_no_trigger"
    termination_reason = "no_coarse_trigger"

    def _active_coarse_start_delay_us():
        value = tail_plan.get("retargeted_coarse_start_delay_us")
        if value is None:
            value = tail_plan.get("coarse_start_delay_us")
        return int(value)

    def _pending_coarse_delays():
        existing = {
            int(dict(summary or {}).get("delay_us"))
            for summary in list(coarse_summaries or [])
            if dict(summary or {}).get("delay_us") not in (None, "")
        }
        start_delay_us = _active_coarse_start_delay_us()
        return [
            int(start_delay_us + (idx * tail_plan["coarse_step_us"]))
            for idx in range(int(tail_plan["planned_coarse_delay_count"]))
            if int(start_delay_us + (idx * tail_plan["coarse_step_us"])) not in existing
        ]

    coarse_delays = _pending_coarse_delays()
    coarse_idx = 0
    while coarse_idx < len(coarse_delays):
        delay_us = int(coarse_delays[coarse_idx])
        capture_budget_state = online_cal_mod.consume_online_stream_budget(
            capture_budget_state,
            phase="tail_phase",
            count=1,
        )
        summary = _build_tail_delay_summary(
            rows_by_delay,
            delay_from_emergence_us=int(delay_us),
            baseline_width_px=baseline_width_px,
        )
        coarse_summaries.append(summary)
        if bool(summary.get("delay_accepted")):
            consecutive_failed = 0
        else:
            consecutive_failed += 1
        accepted_nontriggers = sorted(
            int(dict(item or {}).get("delay_us"))
            for item in coarse_summaries
            if bool(dict(item or {}).get("delay_accepted"))
            and not bool(dict(item or {}).get("triggered_coarse"))
            and dict(item or {}).get("delay_us") not in (None, "")
        )
        accepted_triggers = sorted(
            (int(dict(item or {}).get("delay_us")), dict(item or {}))
            for item in coarse_summaries
            if bool(dict(item or {}).get("delay_accepted"))
            and bool(dict(item or {}).get("triggered_coarse"))
            and dict(item or {}).get("delay_us") not in (None, "")
        )
        if accepted_triggers:
            trigger_delay_us = int(accepted_triggers[0][0])
            trigger_reason = str(accepted_triggers[0][1].get("trigger_reason") or trigger_reason or "")
            eligible_nontriggers = [
                int(value) for value in accepted_nontriggers if int(value) < int(trigger_delay_us)
            ]
            last_nontrigger_delay_us = max(eligible_nontriggers) if eligible_nontriggers else None
        else:
            trigger_delay_us = None
            trigger_reason = None
            last_nontrigger_delay_us = max(accepted_nontriggers) if accepted_nontriggers else None

        decision = online_tail_mod.decide_online_stream_tail_next_action(
            mode="coarse",
            delay_summary=summary,
            capture_budget=capture_budget_state,
            consecutive_failed_delays=consecutive_failed,
            attempted_delay_count=len(coarse_summaries),
            planned_delay_count=int(tail_plan["planned_coarse_delay_count"]),
            has_last_nontrigger=bool(last_nontrigger_delay_us is not None),
            current_delay_us=delay_us,
            coarse_step_us=int(tail_plan["coarse_step_us"]),
            coarse_start_delay_us=_active_coarse_start_delay_us(),
            tail_retarget_count=int(tail_plan.get("tail_retarget_count") or 0),
            emergence_time_us=0,
        )
        action = str(decision.get("action") or "")
        if action == "continue":
            coarse_idx += 1
            continue
        if action == "retarget_coarse":
            tail_plan["tail_retarget_count"] = int(
                decision.get("tail_retarget_count") or (int(tail_plan.get("tail_retarget_count") or 0) + 1)
            )
            tail_plan["retargeted_coarse_start_delay_us"] = int(
                decision.get("retargeted_coarse_start_delay_us")
            )
            coarse_delays = _pending_coarse_delays()
            coarse_idx = 0
            continue
        if action == "switch_to_refine":
            trigger_reason = str(decision.get("trigger_reason") or trigger_reason or "")
            refine_delays = online_tail_mod.build_online_stream_tail_refine_plan(
                last_coarse_nontrigger_delay_us=last_nontrigger_delay_us,
                first_coarse_trigger_delay_us=trigger_delay_us,
                refine_step_us=int(tail_plan["refine_step_us"]),
                coarse_step_us=int(tail_plan["coarse_step_us"]),
                planned_coarse_start_delay_us=_active_coarse_start_delay_us(),
            )
            for refine_idx, refine_delay_us in enumerate(refine_delays, start=1):
                capture_budget_state = online_cal_mod.consume_online_stream_budget(
                    capture_budget_state,
                    phase="tail_phase",
                    count=1,
                )
                refine_summary = _build_tail_delay_summary(
                    rows_by_delay,
                    delay_from_emergence_us=int(refine_delay_us),
                    baseline_width_px=baseline_width_px,
                )
                refine_summaries.append(refine_summary)
                refine_decision = online_tail_mod.decide_online_stream_tail_next_action(
                    mode="refine",
                    delay_summary=refine_summary,
                    capture_budget=capture_budget_state,
                    attempted_delay_count=refine_idx,
                    planned_delay_count=len(refine_delays),
                )
                refine_action = str(refine_decision.get("action") or "")
                if refine_action == "continue":
                    continue
                phase_status = str(refine_decision.get("tail_phase_status") or "captured")
                termination_reason = str(refine_decision.get("termination_reason") or "")
                trigger_reason = str(refine_decision.get("trigger_reason") or trigger_reason or "")
                break
            else:
                phase_status = "advisory_coarse_only"
                termination_reason = "coarse_trigger_fallback"
            break

        phase_status = str(decision.get("tail_phase_status") or "unresolved_no_trigger")
        termination_reason = str(decision.get("termination_reason") or "")
        trigger_reason = str(decision.get("trigger_reason") or trigger_reason or "")
        break

    return online_tail_mod.resolve_online_stream_tail_result(
        flow_fit_result=flow_fit_result,
        tail_plan=tail_plan,
        coarse_summaries=coarse_summaries,
        refine_summaries=refine_summaries,
        trigger_bracket={
            "tail_phase_status": phase_status,
            "termination_reason": termination_reason,
            "trigger_delay_us": trigger_delay_us,
            "last_nontrigger_delay_us": last_nontrigger_delay_us,
            "trigger_reason": trigger_reason,
            "tail_retarget_count": int(tail_plan.get("tail_retarget_count") or 0),
            "retargeted_coarse_start_delay_us": tail_plan.get("retargeted_coarse_start_delay_us"),
        },
    )


def test_sparse_online_tail_replay_matches_dense_offline_tail_start_with_advisory_coarse_fallbacks():
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
        if str(result.get("tail_phase", {}).get("status") or "") not in {
            "captured",
            "advisory_coarse_only",
        }:
            continue
        predicted_tail_start_delay_us = _to_int(
            result.get("tail_phase", {}).get("tail_start_delay_from_emergence_us")
        )
        if predicted_tail_start_delay_us is None:
            continue
        errors.append(abs(int(predicted_tail_start_delay_us) - int(gold_tail_start_delay_us)))

    assert len(errors) >= 20
    sorted_errors = sorted(int(value) for value in errors)
    median_error = sorted_errors[len(sorted_errors) // 2]
    worst_error = max(sorted_errors)

    assert median_error <= 250
    assert worst_error <= 350
