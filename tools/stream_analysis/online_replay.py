from __future__ import annotations

import json
from pathlib import Path

from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import online_fit as online_fit_mod
from tools.stream_analysis import online_tail as online_tail_mod


def _to_int(value):
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:
        return None


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _iter_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _accepted_measurements(frame_rows: list[dict], *, phases: tuple[str, ...]) -> list[dict]:
    measurements = []
    for row in list(frame_rows or []):
        record = dict(row or {})
        if str(record.get("phase") or "") not in phases:
            continue
        if str(record.get("status") or "") != "accepted":
            continue
        delay_us = _to_int(record.get("delay_us"))
        delay_from_emergence_us = _to_int(record.get("delay_from_emergence_us"))
        replicate_index = _to_int(record.get("replicate_index"))
        if delay_us is None or delay_from_emergence_us is None or replicate_index is None:
            continue
        measurements.append(
            online_cal_mod.build_online_stream_measurement_row(
                phase=str(record.get("phase") or ""),
                delay_us=delay_us,
                delay_from_emergence_us=delay_from_emergence_us,
                replicate_index=replicate_index,
                width_px=record.get("attached_width_px"),
                visible_volume_nl=record.get("visible_volume_nl"),
                qc_pass=True,
                image_ref=dict(record.get("image_ref") or {}),
                nozzle_qc_pass=dict(record.get("qc") or {}).get("nozzle_qc_pass"),
                silhouette_qc_pass=dict(record.get("qc") or {}).get("silhouette_qc_pass"),
                attached_bottom_clearance_px=record.get("attached_bottom_clearance_px"),
            )
        )
    return measurements


def _group_delay_summaries(frame_rows: list[dict], *, phase, baseline_width_px=None) -> list[dict]:
    phase_labels = (
        {str(item) for item in phase}
        if isinstance(phase, (list, tuple, set))
        else {str(phase)}
    )
    grouped = {}
    for row in list(frame_rows or []):
        record = dict(row or {})
        if str(record.get("phase") or "") not in phase_labels:
            continue
        delay_key = _to_int(record.get("delay_us"))
        if delay_key is None:
            continue
        grouped.setdefault(delay_key, []).append(record)

    summaries = []
    for delay_us in sorted(grouped):
        rows = list(grouped.get(delay_us) or [])
        if phase == "flow_rate":
            summaries.append(online_cal_mod.summarize_online_stream_flow_delay(rows))
        else:
            summaries.append(
                online_tail_mod.summarize_online_stream_tail_delay(
                    rows,
                    baseline_width_px=baseline_width_px,
                )
            )
    return summaries


def _replay_tail_trigger_bracket(
    scout_summaries: list[dict],
    backtrack_summaries: list[dict],
    *,
    tail_plan: dict | None = None,
    flow_delay_summaries: list[dict] | None = None,
) -> dict:
    plan = dict(tail_plan or {})
    ordered_scout = sorted(
        [dict(row or {}) for row in list(scout_summaries or [])],
        key=lambda item: (_to_int(item.get("delay_from_emergence_us")) or 0),
    )
    landmark_summary = None
    for summary in ordered_scout:
        if bool(summary.get("delay_accepted")) and bool(summary.get("landmark_detected")):
            landmark_summary = dict(summary)
            break

    if landmark_summary is None:
        return {
            "tail_phase_status": "unresolved_no_landmark",
            "termination_reason": "no_scout_landmark",
            "landmark_delay_us": None,
            "backtrack_left_delay_us": None,
            "landmark_reason": None,
            "warnings": ["unresolved_no_landmark"],
        }

    landmark_delay_us = _to_int(landmark_summary.get("delay_us"))
    previous_scout_delays = [
        _to_int(dict(item or {}).get("delay_us"))
        for item in ordered_scout
        if _to_int(dict(item or {}).get("delay_us")) is not None
        and _to_int(dict(item or {}).get("delay_us")) < int(landmark_delay_us or 0)
    ]
    if previous_scout_delays:
        backtrack_left_delay_us = int(previous_scout_delays[-1])
    else:
        backtrack_left_delay_us = _to_int(plan.get("scout_anchor_delay_us"))
        if backtrack_left_delay_us is None:
            accepted_flow_delays = [
                _to_int(dict(item or {}).get("delay_us"))
                for item in list(flow_delay_summaries or [])
                if bool(dict(item or {}).get("delay_accepted"))
                and _to_int(dict(item or {}).get("delay_us")) is not None
            ]
            if accepted_flow_delays:
                backtrack_left_delay_us = int(max(accepted_flow_delays))

    return {
        "tail_phase_status": "",
        "termination_reason": "",
        "landmark_delay_us": landmark_delay_us,
        "backtrack_left_delay_us": backtrack_left_delay_us,
        "landmark_reason": landmark_summary.get("landmark_reason"),
        "warnings": [],
    }


def _compare_values(stored, replayed, *, tol=1e-9):
    left_float = _to_float(stored)
    right_float = _to_float(replayed)
    if left_float is not None or right_float is not None:
        if left_float is None or right_float is None:
            return {"matches": False, "stored": stored, "replayed": replayed, "abs_diff": None}
        return {
            "matches": abs(float(left_float) - float(right_float)) <= float(tol),
            "stored": float(left_float),
            "replayed": float(right_float),
            "abs_diff": abs(float(left_float) - float(right_float)),
        }
    left_int = _to_int(stored)
    right_int = _to_int(replayed)
    if left_int is not None or right_int is not None:
        if left_int is None or right_int is None:
            return {"matches": False, "stored": stored, "replayed": replayed, "abs_diff": None}
        return {
            "matches": int(left_int) == int(right_int),
            "stored": int(left_int),
            "replayed": int(right_int),
            "abs_diff": abs(int(left_int) - int(right_int)),
        }
    return {
        "matches": stored == replayed,
        "stored": stored,
        "replayed": replayed,
        "abs_diff": None,
    }


def _compare_optional_stored_field(stored_obj: dict, key: str, replayed, *, tol=1e-9):
    record = dict(stored_obj or {})
    if str(key) not in record:
        return {
            "matches": True,
            "stored": None,
            "replayed": replayed,
            "abs_diff": None,
            "skipped": True,
        }
    comparison = _compare_values(record.get(str(key)), replayed, tol=tol)
    comparison["skipped"] = False
    return comparison


def _compare_warning_sets(stored, replayed):
    left = sorted({str(item or "").strip() for item in list(stored or []) if str(item or "").strip()})
    right = sorted({str(item or "").strip() for item in list(replayed or []) if str(item or "").strip()})
    return {
        "matches": left == right,
        "stored": left,
        "replayed": right,
        "abs_diff": None,
    }


def _compare_optional_warning_set(stored_obj: dict, key: str, replayed):
    record = dict(stored_obj or {})
    if str(key) not in record:
        return {
            "matches": True,
            "stored": None,
            "replayed": sorted(
                {str(item or "").strip() for item in list(replayed or []) if str(item or "").strip()}
            ),
            "abs_diff": None,
            "skipped": True,
        }
    comparison = _compare_warning_sets(record.get(str(key)), replayed)
    comparison["skipped"] = False
    return comparison


def _compare_jsonish(stored, replayed):
    return {
        "matches": stored == replayed,
        "stored": stored,
        "replayed": replayed,
        "abs_diff": None,
    }


def _compare_optional_contract_field(stored_obj: dict, replayed_obj: dict, key: str, *, tol=1e-9):
    stored_record = dict(stored_obj or {})
    replayed_record = dict(replayed_obj or {})
    if str(key) not in stored_record or str(key) not in replayed_record:
        return {
            "matches": True,
            "stored": stored_record.get(str(key)),
            "replayed": replayed_record.get(str(key)),
            "abs_diff": None,
            "skipped": True,
        }
    comparison = _compare_values(
        stored_record.get(str(key)),
        replayed_record.get(str(key)),
        tol=tol,
    )
    comparison["skipped"] = False
    return comparison


def _compare_optional_contract_jsonish(stored_obj: dict, replayed_obj: dict, key: str):
    stored_record = dict(stored_obj or {})
    replayed_record = dict(replayed_obj or {})
    if str(key) not in stored_record or str(key) not in replayed_record:
        return {
            "matches": True,
            "stored": stored_record.get(str(key)),
            "replayed": replayed_record.get(str(key)),
            "abs_diff": None,
            "skipped": True,
        }
    comparison = _compare_jsonish(
        stored_record.get(str(key)),
        replayed_record.get(str(key)),
    )
    comparison["skipped"] = False
    return comparison


def _compare_optional_contract_warning_set(stored_obj: dict, replayed_obj: dict, key: str):
    stored_record = dict(stored_obj or {})
    replayed_record = dict(replayed_obj or {})
    if str(key) not in stored_record or str(key) not in replayed_record:
        return {
            "matches": True,
            "stored": stored_record.get(str(key)),
            "replayed": replayed_record.get(str(key)),
            "abs_diff": None,
            "skipped": True,
        }
    comparison = _compare_warning_sets(
        stored_record.get(str(key)),
        replayed_record.get(str(key)),
    )
    comparison["skipped"] = False
    return comparison


def replay_online_stream_run(run_dir: str | Path) -> dict:
    run_path = Path(run_dir).resolve()
    plan_snapshot = _load_json(run_path / "plan_snapshot.json")
    prior_resolution = _load_json(run_path / "prior_resolution.json")
    flow_fit_artifact = _load_json(run_path / "flow_fit.json")
    tail_fit_artifact = _load_json(run_path / "tail_fit.json")
    frame_rows = _iter_jsonl(run_path / "frames.jsonl")

    flow_measurements = _accepted_measurements(frame_rows, phases=("flow_rate",))
    flow_delay_summaries = _group_delay_summaries(frame_rows, phase="flow_rate")
    replay_flow_fit = online_fit_mod.fit_online_stream_flow_phase(
        measurements=flow_measurements,
        delay_summaries=flow_delay_summaries,
    )

    baseline_width_px = _to_float(replay_flow_fit.get("steady_width_baseline_px"))
    if baseline_width_px is None:
        baseline_width_px = _to_float(_load_json(run_path / "flow_fit.json").get("fit", {}).get("steady_width_baseline_px"))
    scout_summaries = _group_delay_summaries(
        frame_rows,
        phase=("tail_scout", "tail_coarse"),
        baseline_width_px=baseline_width_px,
    )
    backtrack_summaries = _group_delay_summaries(
        frame_rows,
        phase=("tail_backtrack", "tail_refine"),
        baseline_width_px=baseline_width_px,
    )
    stored_tail_plan = dict(tail_fit_artifact.get("tail_plan") or {})
    trigger_bracket = _replay_tail_trigger_bracket(
        scout_summaries,
        backtrack_summaries,
        tail_plan=stored_tail_plan,
        flow_delay_summaries=flow_delay_summaries,
    )
    replay_tail_result = online_tail_mod.resolve_online_stream_tail_result(
        flow_fit_result=dict(replay_flow_fit or {}),
        tail_plan=stored_tail_plan,
        scout_summaries=scout_summaries,
        backtrack_summaries=backtrack_summaries,
        trigger_bracket=trigger_bracket,
        flow_delay_summaries=flow_delay_summaries,
    )

    stored_flow_fit = dict(flow_fit_artifact.get("fit") or {})
    stored_tail_result = dict(tail_fit_artifact.get("result") or {})
    stored_tail_phase = dict(stored_tail_result.get("tail_phase") or {})
    replay_tail_phase = dict(replay_tail_result.get("tail_phase") or {})
    stored_prior_contract = dict(plan_snapshot.get("priors") or {})
    stored_prior_lookup = dict(prior_resolution.get("lookup") or {})
    replay_prior_lookup = dict(stored_prior_contract.get("lookup") or {})
    comparison = {
        "prior_lookup_looked_up": _compare_optional_contract_field(
            stored_prior_lookup,
            replay_prior_lookup,
            "looked_up",
        ),
        "prior_lookup_candidate_found": _compare_optional_contract_field(
            stored_prior_lookup,
            replay_prior_lookup,
            "candidate_found",
        ),
        "prior_candidate_prior": _compare_optional_contract_jsonish(
            prior_resolution,
            stored_prior_contract,
            "candidate_prior",
        ),
        "prior_applied_prior": _compare_optional_contract_jsonish(
            prior_resolution,
            stored_prior_contract,
            "applied_prior",
        ),
        "prior_fallback_reason": _compare_optional_contract_field(
            prior_resolution,
            stored_prior_contract,
            "fallback_reason",
        ),
        "prior_warnings": _compare_optional_contract_warning_set(
            prior_resolution,
            stored_prior_contract,
            "warnings",
        ),
        "flow_rate_nl_per_us": _compare_values(
            stored_flow_fit.get("flow_rate_nl_per_us"),
            replay_flow_fit.get("flow_rate_nl_per_us"),
            tol=1e-6,
        ),
        "flow_fit_status": _compare_values(
            stored_flow_fit.get("fit_status"),
            replay_flow_fit.get("fit_status"),
        ),
        "steady_width_baseline_px": _compare_optional_stored_field(
            stored_flow_fit,
            "steady_width_baseline_px",
            replay_flow_fit.get("steady_width_baseline_px"),
            tol=1e-6,
        ),
        "flow_fit_delay_start_from_emergence_us": _compare_optional_stored_field(
            stored_flow_fit,
            "flow_fit_delay_start_from_emergence_us",
            replay_flow_fit.get("flow_fit_delay_start_from_emergence_us"),
        ),
        "flow_fit_delay_end_from_emergence_us": _compare_optional_stored_field(
            stored_flow_fit,
            "flow_fit_delay_end_from_emergence_us",
            replay_flow_fit.get("flow_fit_delay_end_from_emergence_us"),
        ),
        "flow_fit_point_count": _compare_optional_stored_field(
            stored_flow_fit,
            "flow_fit_point_count",
            replay_flow_fit.get("flow_fit_point_count"),
        ),
        "steady_r2": _compare_optional_stored_field(
            stored_flow_fit,
            "steady_r2",
            replay_flow_fit.get("steady_r2"),
            tol=1e-6,
        ),
        "steady_nrmse": _compare_optional_stored_field(
            stored_flow_fit,
            "steady_nrmse",
            replay_flow_fit.get("steady_nrmse"),
            tol=1e-6,
        ),
        "flow_fit_outlier_prune_status": _compare_optional_stored_field(
            stored_flow_fit,
            "flow_fit_outlier_prune_status",
            replay_flow_fit.get("flow_fit_outlier_prune_status"),
        ),
        "flow_fit_dropped_outlier_delay_from_emergence_us": _compare_optional_stored_field(
            stored_flow_fit,
            "flow_fit_dropped_outlier_delay_from_emergence_us",
            replay_flow_fit.get("flow_fit_dropped_outlier_delay_from_emergence_us"),
        ),
        "tail_start_delay_from_emergence_us": _compare_values(
            stored_tail_phase.get("tail_start_delay_from_emergence_us"),
            replay_tail_phase.get("tail_start_delay_from_emergence_us"),
        ),
        "tail_search_method": _compare_optional_stored_field(
            stored_tail_phase,
            "search_method",
            replay_tail_phase.get("search_method"),
        ),
        "tail_phase_status": _compare_values(
            stored_tail_phase.get("status"),
            replay_tail_phase.get("status"),
        ),
        "predicted_stream_duration_us": _compare_optional_stored_field(
            stored_tail_result,
            "predicted_stream_duration_us",
            replay_tail_result.get("predicted_stream_duration_us"),
        ),
        "tail_termination_reason": _compare_optional_stored_field(
            stored_tail_phase,
            "termination_reason",
            replay_tail_phase.get("termination_reason"),
        ),
        "tail_trigger_delay_from_emergence_us": _compare_optional_stored_field(
            stored_tail_phase,
            "landmark_delay_from_emergence_us",
            replay_tail_phase.get("landmark_delay_from_emergence_us"),
        ),
        "tail_trigger_reason": _compare_optional_stored_field(
            stored_tail_phase,
            "landmark_reason",
            replay_tail_phase.get("landmark_reason"),
        ),
        "tail_last_nontrigger_delay_from_emergence_us": _compare_optional_stored_field(
            stored_tail_phase,
            "backtrack_window_start_delay_from_emergence_us",
            replay_tail_phase.get("backtrack_window_start_delay_from_emergence_us"),
        ),
        "tail_start_evidence": _compare_optional_stored_field(
            stored_tail_phase,
            "tail_start_evidence",
            replay_tail_phase.get("tail_start_evidence"),
        ),
        "tail_retarget_count": _compare_optional_stored_field(
            stored_tail_phase,
            "tail_retarget_count",
            replay_tail_phase.get("tail_retarget_count"),
        ),
        "retargeted_coarse_start_delay_us": _compare_optional_stored_field(
            stored_tail_phase,
            "retargeted_coarse_start_delay_us",
            replay_tail_phase.get("retargeted_coarse_start_delay_us"),
        ),
        "tail_warnings": _compare_optional_warning_set(
            stored_tail_phase,
            "warnings",
            replay_tail_phase.get("warnings"),
        ),
        "predicted_volume_nl": _compare_values(
            stored_tail_result.get("predicted_volume_nl"),
            replay_tail_result.get("predicted_volume_nl"),
            tol=1e-6,
        ),
    }
    comparison["all_match"] = all(bool(item.get("matches")) for item in comparison.values())

    return {
        "run_dir": str(run_path),
        "artifacts_present": {
            "plan_snapshot": bool(plan_snapshot),
            "prior_resolution": bool(prior_resolution),
            "flow_fit": bool(flow_fit_artifact),
            "tail_fit": bool(tail_fit_artifact),
            "frames": bool(frame_rows),
        },
        "replayed": {
            "flow_fit": dict(replay_flow_fit or {}),
            "tail_result": dict(replay_tail_result or {}),
            "flow_delay_summaries": flow_delay_summaries,
            "scout_delay_summaries": scout_summaries,
            "backtrack_delay_summaries": backtrack_summaries,
            "coarse_delay_summaries": scout_summaries,
            "refine_delay_summaries": backtrack_summaries,
        },
        "stored": {
            "plan_snapshot": plan_snapshot,
            "prior_resolution": prior_resolution,
            "flow_fit": flow_fit_artifact,
            "tail_fit": tail_fit_artifact,
        },
        "comparison": comparison,
    }
