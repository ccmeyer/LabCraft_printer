from __future__ import annotations

from tools.stream_analysis import online_calibration as online_cal_mod


def to_int(value):
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except Exception:
        return None


def to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def feature_row_is_flow_accepted(row: dict) -> bool:
    return bool(
        str(row.get("silhouette_status") or "") == "ok"
        and to_float(row.get("attached_near_nozzle_width_median_px")) is not None
        and to_float(row.get("total_visible_volume_nl")) is not None
        and (to_float(row.get("min_accepted_fluid_distance_from_bottom_px")) or 0.0) > 96.0
    )


def _feature_row_is_flow_soft_boundary(row: dict, *, soft_bottom_clearance_px: int) -> bool:
    if not feature_row_is_flow_accepted(row):
        return False
    clearance_px = to_float(row.get("min_accepted_fluid_distance_from_bottom_px"))
    if clearance_px is None:
        return False
    return float(clearance_px) <= float(soft_bottom_clearance_px)


def _feature_row_is_flow_hard_boundary(row: dict) -> bool:
    clearance_px = to_float(row.get("min_accepted_fluid_distance_from_bottom_px"))
    if clearance_px is None:
        return False
    return float(clearance_px) <= 96.0


def _select_feature_row(
    rows_by_delay: dict[int, dict],
    *,
    target_offset_us: int,
    used_offsets: set[int],
    max_delta_us: int = 60,
) -> tuple[int | None, dict | None]:
    exact_row = rows_by_delay.get(int(target_offset_us))
    if exact_row is not None and int(target_offset_us) not in used_offsets:
        return int(target_offset_us), exact_row

    candidate_offsets = []
    for offset_us in sorted(int(value) for value in rows_by_delay.keys()):
        if int(offset_us) in used_offsets:
            continue
        if abs(int(offset_us) - int(target_offset_us)) <= int(max_delta_us):
            candidate_offsets.append(int(offset_us))
    if not candidate_offsets:
        return None, None
    best_offset_us = min(
        candidate_offsets,
        key=lambda offset_us: (abs(int(offset_us) - int(target_offset_us)), int(offset_us)),
    )
    return int(best_offset_us), rows_by_delay.get(int(best_offset_us))


def _build_flow_summary_from_feature_row(
    *,
    offset_from_emergence_us: int,
    feature_row: dict,
    capture_id_prefix: str,
) -> tuple[dict, dict | None]:
    delay_us = to_int(feature_row.get("flash_delay_us")) or int(offset_from_emergence_us)
    capture_id = str(feature_row.get("capture_id") or f"{capture_id_prefix}_{offset_from_emergence_us}")
    accepted = feature_row_is_flow_accepted(feature_row)
    hard_boundary = _feature_row_is_flow_hard_boundary(feature_row)
    soft_boundary = _feature_row_is_flow_soft_boundary(
        feature_row,
        soft_bottom_clearance_px=int(
            online_cal_mod.DEFAULT_ONLINE_STREAM_POLICY["flow_soft_bottom_clearance_px"]
        ),
    )
    warnings = []
    if soft_boundary:
        warnings.append("detached_near_bottom_warning")
    if hard_boundary:
        warnings.append("attached_bottom_guard_hit")
    status = "accepted"
    if not accepted:
        status = "rejected_bottom_guard" if hard_boundary else "rejected_replay_qc"
    frame_row = online_cal_mod.build_online_stream_frame_row(
        phase="flow_rate",
        status=status,
        delay_us=int(delay_us),
        delay_from_emergence_us=int(offset_from_emergence_us),
        replicate_index=1,
        qc={"measurement_qc_pass": bool(accepted)},
        image_ref={"capture_id": capture_id},
        warnings=warnings if not accepted else [],
        attached_width_px=to_float(feature_row.get("attached_near_nozzle_width_median_px")),
        visible_volume_nl=to_float(feature_row.get("total_visible_volume_nl")),
        attached_bottom_clearance_px=to_float(feature_row.get("min_accepted_fluid_distance_from_bottom_px")),
        min_accepted_fluid_distance_from_bottom_px=to_float(
            feature_row.get("min_accepted_fluid_distance_from_bottom_px")
        ),
        accepted_component_count=to_int(feature_row.get("accepted_component_count")) or 0,
        accepted_detached_component_count=to_int(feature_row.get("accepted_detached_component_count")) or 0,
        detached_near_bottom_warning=bool(soft_boundary),
        attached_bottom_guard_hit=bool(hard_boundary),
    )
    delay_summary = online_cal_mod.summarize_online_stream_flow_delay([frame_row])
    measurement = None
    if accepted:
        measurement = online_cal_mod.build_online_stream_measurement_row(
            phase="flow_rate",
            delay_us=int(delay_us),
            delay_from_emergence_us=int(offset_from_emergence_us),
            replicate_index=1,
            width_px=to_float(feature_row.get("attached_near_nozzle_width_median_px")),
            visible_volume_nl=to_float(feature_row.get("total_visible_volume_nl")),
            qc_pass=True,
            image_ref={"capture_id": capture_id},
        )
    return delay_summary, measurement


def build_adaptive_flow_replay_inputs(
    rows_by_delay: dict[int, dict],
    *,
    fit_module,
    capture_id_prefix: str = "replay",
) -> tuple[list[dict], list[dict]]:
    plan = online_cal_mod.build_online_stream_flow_plan(emergence_time_us=0)
    start_offset_us = int(plan["start_offset_from_emergence_us"])
    scout_step_us = int(plan["scout_step_us"])
    target_delay_count = int(plan["target_delay_count"])
    min_accepted_delays = int(plan["min_accepted_delays"])
    max_capture_count = int(plan["max_capture_count"])
    ci_target = float(plan["ci95_relative_width_target"])
    ci_extension_step_us = int(plan["ci_extension_step_us"])

    measurements = []
    delay_summaries = []
    used_offsets = set()
    sampled_offsets = []
    right_boundary_offset_us = None
    right_boundary_fixed = False
    last_accepted_offset_us = None
    last_non_soft_accepted_offset_us = None

    def _append_offset(selected_offset_us: int, feature_row: dict):
        nonlocal right_boundary_offset_us, right_boundary_fixed
        nonlocal last_accepted_offset_us, last_non_soft_accepted_offset_us
        delay_summary, measurement = _build_flow_summary_from_feature_row(
            offset_from_emergence_us=int(selected_offset_us),
            feature_row=feature_row,
            capture_id_prefix=str(capture_id_prefix),
        )
        delay_summaries.append(delay_summary)
        if measurement is not None:
            measurements.append(measurement)
            last_accepted_offset_us = int(selected_offset_us)
            if not bool(delay_summary.get("detached_near_bottom_warning")):
                last_non_soft_accepted_offset_us = int(selected_offset_us)
        sampled_offsets.append(int(selected_offset_us))
        used_offsets.add(int(selected_offset_us))
        if bool(delay_summary.get("attached_bottom_guard_hit")) and not bool(right_boundary_fixed):
            right_boundary_fixed = True
            right_boundary_offset_us = (
                last_non_soft_accepted_offset_us
                or last_accepted_offset_us
                or int(start_offset_us)
            )
        elif bool(delay_summary.get("delay_accepted")) and bool(delay_summary.get("detached_near_bottom_warning")) and not bool(right_boundary_fixed):
            right_boundary_fixed = True
            right_boundary_offset_us = int(selected_offset_us)

    for scout_index in range(int(min(target_delay_count, max_capture_count))):
        selected_offset_us, feature_row = _select_feature_row(
            rows_by_delay,
            target_offset_us=int(start_offset_us + (scout_index * scout_step_us)),
            used_offsets=used_offsets,
        )
        if feature_row is None or selected_offset_us is None:
            break
        _append_offset(int(selected_offset_us), feature_row)
        if bool(right_boundary_fixed):
            break

    if right_boundary_offset_us is None:
        right_boundary_offset_us = (
            last_non_soft_accepted_offset_us
            or last_accepted_offset_us
            or int(start_offset_us)
        )

    target_offsets = online_cal_mod.build_online_stream_flow_target_offsets(
        start_offset_us=int(start_offset_us),
        end_offset_us=int(right_boundary_offset_us),
        target_delay_count=int(target_delay_count),
    )
    for target_offset_us in list(target_offsets):
        if len(delay_summaries) >= int(max_capture_count):
            break
        if any(abs(int(existing_offset_us) - int(target_offset_us)) <= 35 for existing_offset_us in sampled_offsets):
            continue
        selected_offset_us, feature_row = _select_feature_row(
            rows_by_delay,
            target_offset_us=int(target_offset_us),
            used_offsets=used_offsets,
        )
        if feature_row is None or selected_offset_us is None:
            continue
        _append_offset(int(selected_offset_us), feature_row)

    while len(delay_summaries) < int(max_capture_count):
        accepted_delay_count = sum(
            1 for row in delay_summaries if bool((row or {}).get("delay_accepted"))
        )
        fit_result = {}
        if int(accepted_delay_count) >= int(min_accepted_delays):
            fit_result = dict(
                fit_module.fit_online_stream_flow_phase(
                    measurements=measurements,
                    delay_summaries=delay_summaries,
                )
                or {}
            )
        try:
            ci_relative_width = float(fit_result.get("steady_rate_ci95_relative_width"))
        except Exception:
            ci_relative_width = None
        if (
            int(accepted_delay_count) >= int(min_accepted_delays)
            and ci_relative_width is not None
            and float(ci_relative_width) <= float(ci_target)
        ):
            break

        if not bool(right_boundary_fixed):
            next_target_offset_us = int(
                (max(sampled_offsets) if sampled_offsets else int(start_offset_us))
                + int(ci_extension_step_us)
            )
        else:
            next_target_offset_us = online_cal_mod.select_online_stream_flow_gap_midpoint(
                sampled_offsets_from_emergence_us=sampled_offsets,
                start_offset_us=int(start_offset_us),
                end_offset_us=int(right_boundary_offset_us),
            )
            if next_target_offset_us is None:
                break
        selected_offset_us, feature_row = _select_feature_row(
            rows_by_delay,
            target_offset_us=int(next_target_offset_us),
            used_offsets=used_offsets,
        )
        if feature_row is None or selected_offset_us is None:
            break
        _append_offset(int(selected_offset_us), feature_row)

    return measurements, delay_summaries
