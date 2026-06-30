from __future__ import annotations

import cv2
import numpy as np

from tools.stream_analysis import online_calibration as online_cal_mod
from tools.stream_analysis import silhouette as silhouette_mod
from tools.stream_analysis import volume as volume_mod


_ROI_WIDTH_FRAC = 0.35
_ROI_TOP_FRAC = 0.10
_ROI_BOTTOM_FRAC = 1.0
_CORRIDOR_WIDTH_FRAC = 0.70
_WIDTH_ROOT_IQR_MIN_PX = 12.0
_WIDTH_ROOT_IQR_FRAC = 0.10
_WIDTH_ROOT_HALF_DELTA_MIN_PX = 16.0
_WIDTH_ROOT_HALF_DELTA_FRAC = 0.12
_WIDTH_CANDIDATE_IQR_MIN_PX = 8.0
_WIDTH_CANDIDATE_IQR_FRAC = 0.08
_WIDTH_CANDIDATE_NARROWER_MIN_PX = 18.0
_WIDTH_CANDIDATE_NARROWER_FRAC = 0.15
_WIDTH_MAX_CANDIDATE_START_DELTA_PX = 100


def _resolved_analysis_config(config: dict | None = None) -> dict:
    merged = dict(online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG)
    for key, default_value in online_cal_mod.DEFAULT_ONLINE_STREAM_ANALYSIS_CONFIG.items():
        if isinstance(config, dict) and key in config:
            if isinstance(default_value, bool):
                merged[key] = bool(config.get(key))
                continue
            if isinstance(default_value, float):
                try:
                    merged[key] = float(config.get(key))
                except Exception:
                    merged[key] = float(default_value)
            else:
                try:
                    merged[key] = int(config.get(key))
                except Exception:
                    merged[key] = int(default_value)
    extra_defaults = {
        "tail_width_window_delay_lock_enabled": True,
        "tail_width_window_monotonic_by_delay_enabled": True,
    }
    for key, default_value in extra_defaults.items():
        if isinstance(config, dict) and key in config:
            merged[key] = bool(config.get(key))
        else:
            merged[key] = bool(default_value)
    return merged


def _tracked_row(nozzle_center_px) -> dict:
    if nozzle_center_px is None or len(nozzle_center_px) < 2:
        raise ValueError("Locked nozzle center is required for online stream analysis.")
    x_px = float(nozzle_center_px[0])
    y_px = float(nozzle_center_px[1])
    return {
        "tracked_nozzle_x_px": x_px,
        "tracked_nozzle_y_px": y_px,
        "tracked_confidence": 1.0,
        "raw_mode": "locked_emergence_nozzle",
        "final_mode": "locked_emergence_nozzle",
        "segment_id": 0,
        "shift_event_before": False,
    }


def _adaptive_roi_retry_needed(summary: dict, config: dict) -> bool:
    if not bool(config.get("adaptive_roi_expansion_enabled")):
        return False
    if str(summary.get("silhouette_status") or "") != "ok":
        return False
    reasons = {str(item) for item in list(summary.get("flow_volume_geometry_reasons") or [])}
    geometry_suspect = (
        summary.get("flow_volume_geometry_ok") is False
        or "attached_lower_centerline_span_high" in reasons
    )
    if not geometry_suspect:
        return False
    margin_px = int(config.get("adaptive_roi_edge_margin_px") or 0)
    left_clearance = summary.get("selected_component_corridor_left_clearance_px")
    right_clearance = summary.get("selected_component_corridor_right_clearance_px")
    near_left = left_clearance is not None and int(left_clearance) <= margin_px
    near_right = right_clearance is not None and int(right_clearance) <= margin_px
    return bool(near_left or near_right)


def _frame_row(*, delay_us: int, emergence_time_us: int, capture_ref: dict | None = None, capture_index: int | None = None):
    ref = dict(capture_ref or {})
    return {
        "run_id": "online_stream_runtime",
        "capture_id": ref.get("capture_id"),
        "capture_index": capture_index if capture_index is not None else ref.get("capture_index"),
        "image_relpath": ref.get("image_relpath"),
        "image_exists": True,
        "captured_at_utc": None,
        "flash_delay_us": int(delay_us),
        "delay_from_emergence_us": int(delay_us - int(emergence_time_us)),
    }


def _band_width_metrics(
    stage3_metric_row: dict,
    attached_edge_rows: list[dict],
    *,
    near_nozzle_band_top_px: int,
    near_nozzle_band_height_px: int,
    min_band_valid_rows: int,
    delay_from_emergence_us: int | None = None,
    sticky_window_state: dict | None = None,
    sticky_window_enabled: bool = False,
    window_bank_enabled: bool = True,
    window_delay_lock_enabled: bool = True,
    window_monotonic_by_delay_enabled: bool = True,
    sticky_window_confirm_frames: int = 2,
    sticky_window_min_switch_drop_px: float = 12.0,
    sticky_window_min_switch_drop_frac: float = 0.12,
    sticky_window_max_step_multiplier: int = 1,
) -> dict:
    sticky_active = bool(sticky_window_enabled and sticky_window_state is not None)
    sticky_state = dict(sticky_window_state or {}) if sticky_active else {}

    def _to_int_or_none(value):
        try:
            if value in (None, ""):
                return None
            return int(value)
        except Exception:
            return None

    def _to_float_or_none(value):
        try:
            if value in (None, ""):
                return None
            return float(value)
        except Exception:
            return None

    previous_y0_px = _to_int_or_none(sticky_state.get("selected_band_y0_px"))
    previous_y1_px = _to_int_or_none(sticky_state.get("selected_band_y1_px"))
    current_delay_from_emergence_us = _to_int_or_none(delay_from_emergence_us)
    raw_delay_window_map = sticky_state.get("delay_window_map") if sticky_active else None
    delay_window_map = dict(raw_delay_window_map or {}) if isinstance(raw_delay_window_map, dict) else {}
    locked_window = None
    if bool(window_delay_lock_enabled) and current_delay_from_emergence_us is not None:
        maybe_locked = delay_window_map.get(str(int(current_delay_from_emergence_us)))
        if isinstance(maybe_locked, dict):
            locked_window = dict(maybe_locked)
    locked_step_index = _to_int_or_none(
        None if locked_window is None else locked_window.get("selected_band_step_index")
    )

    def _step_index_for_y0(y0_px, *, root_band_y0_px: int, candidate_step_px: int) -> int | None:
        parsed_y0 = _to_int_or_none(y0_px)
        if parsed_y0 is None:
            return None
        try:
            return int(round((int(parsed_y0) - int(root_band_y0_px)) / float(candidate_step_px)))
        except Exception:
            return None

    def _mode_for_step(step_index: int | None) -> str:
        return "root_band" if int(step_index or 0) <= 0 else "lower_consistent_window"

    def _delay_map_entry(
        *,
        delay_value_us: int | None,
        stats: dict,
        step_index: int,
        attached_width_mode: str,
    ) -> dict | None:
        if delay_value_us is None:
            return None
        return {
            "delay_from_emergence_us": int(delay_value_us),
            "selected_band_step_index": int(step_index),
            "selected_band_y0_px": int(stats["y0_px"]),
            "selected_band_y1_px": int(stats["y1_px"]),
            "attached_width_mode": str(attached_width_mode),
        }

    def _monotonic_bounds(*, delay_value_us: int | None) -> tuple[int | None, int | None]:
        if (
            not bool(window_monotonic_by_delay_enabled)
            or delay_value_us is None
            or not isinstance(delay_window_map, dict)
        ):
            return None, None
        lower_bound = None
        upper_bound = None
        for delay_key, entry in delay_window_map.items():
            if not isinstance(entry, dict):
                continue
            mapped_delay = _to_int_or_none(entry.get("delay_from_emergence_us"))
            if mapped_delay is None:
                mapped_delay = _to_int_or_none(delay_key)
            mapped_step = _to_int_or_none(entry.get("selected_band_step_index"))
            if mapped_delay is None or mapped_step is None:
                continue
            if int(mapped_delay) < int(delay_value_us):
                lower_bound = (
                    int(mapped_step)
                    if lower_bound is None
                    else max(int(lower_bound), int(mapped_step))
                )
            elif int(mapped_delay) > int(delay_value_us):
                upper_bound = (
                    int(mapped_step)
                    if upper_bound is None
                    else min(int(upper_bound), int(mapped_step))
                )
        return lower_bound, upper_bound

    def _sticky_fields(
        *,
        selected_reason: str,
        instant_stats: dict | None = None,
        next_state: dict | None = None,
        candidate_streak: int | None = None,
        switch_blocked: bool = False,
        locked_reused: bool = False,
        locked_invalid: bool = False,
        monotonic_lower_bound_step_index: int | None = None,
        monotonic_upper_bound_step_index: int | None = None,
        monotonic_upward_move_blocked: bool = False,
    ) -> dict:
        return {
            "sticky_window_active": bool(sticky_active and next_state),
            "sticky_window_previous_y0_px": previous_y0_px,
            "sticky_window_previous_y1_px": previous_y1_px,
            "sticky_window_instant_y0_px": (
                None if instant_stats is None else _to_int_or_none(instant_stats.get("y0_px"))
            ),
            "sticky_window_instant_y1_px": (
                None if instant_stats is None else _to_int_or_none(instant_stats.get("y1_px"))
            ),
            "sticky_window_selected_reason": str(selected_reason),
            "sticky_window_candidate_streak": int(candidate_streak or 0),
            "sticky_window_switch_blocked": bool(switch_blocked),
            "window_delay_lock_active": bool(window_delay_lock_enabled and locked_window is not None),
            "window_locked_reused": bool(locked_reused),
            "window_locked_invalid": bool(locked_invalid),
            "window_monotonic_lower_bound_step_index": monotonic_lower_bound_step_index,
            "window_monotonic_upper_bound_step_index": monotonic_upper_bound_step_index,
            "window_monotonic_upward_move_blocked": bool(monotonic_upward_move_blocked),
            "next_sticky_window_state": (
                dict(next_state or {}) if sticky_active else None
            ),
        }

    def _state_for_selected(
        stats: dict,
        *,
        step_index: int | None = None,
        attached_width_mode: str | None = None,
        pending_stats: dict | None = None,
        candidate_streak: int = 0,
    ) -> dict:
        selected_step_index = 0 if step_index is None else int(step_index)
        state = {
            "selected_band_y0_px": int(stats["y0_px"]),
            "selected_band_y1_px": int(stats["y1_px"]),
            "selected_band_step_index": int(selected_step_index),
            "attached_width_mode": str(attached_width_mode or _mode_for_step(selected_step_index)),
        }
        next_delay_window_map = dict(delay_window_map)
        entry = _delay_map_entry(
            delay_value_us=current_delay_from_emergence_us,
            stats=stats,
            step_index=int(selected_step_index),
            attached_width_mode=str(attached_width_mode or _mode_for_step(selected_step_index)),
        )
        if entry is not None and bool(window_delay_lock_enabled):
            next_delay_window_map[str(int(current_delay_from_emergence_us))] = entry
        if next_delay_window_map:
            state["delay_window_map"] = next_delay_window_map
        if pending_stats is not None:
            pending_y0_px = _to_int_or_none(pending_stats.get("y0_px"))
            if pending_y0_px is not None and int(pending_y0_px) != int(stats["y0_px"]):
                state["pending_candidate_y0_px"] = int(pending_y0_px)
                state["pending_candidate_y1_px"] = int(pending_stats["y1_px"])
                state["candidate_streak"] = int(candidate_streak)
                return state
        state["candidate_streak"] = 0
        return state

    def _metrics_payload(
        *,
        selected_stats: dict,
        attached_width_mode: str,
        spread_fallback_triggered: bool,
        candidate_window_count: int,
        root_band_width_px,
        root_band_width_iqr_px,
        root_band_half_delta_px,
        root_band_y0_px: int,
        root_band_y1_px: int,
        sticky_payload: dict,
    ) -> dict:
        payload = {
            "attached_width_px": selected_stats.get("median_width_px"),
            "width_valid_row_count": int(selected_stats.get("valid_row_count") or 0),
            "band_y0_px": int(selected_stats.get("y0_px") or root_band_y0_px),
            "band_y1_px": int(selected_stats.get("y1_px") or root_band_y1_px),
            "attached_width_mode": attached_width_mode,
            "spread_fallback_triggered": bool(spread_fallback_triggered),
            "candidate_window_count": int(candidate_window_count),
            "root_band_width_px": root_band_width_px,
            "root_band_width_iqr_px": root_band_width_iqr_px,
            "root_band_half_delta_px": root_band_half_delta_px,
            "root_band_y0_px": int(root_band_y0_px),
            "root_band_y1_px": int(root_band_y1_px),
            "selected_band_y0_px": int(selected_stats.get("y0_px") or root_band_y0_px),
            "selected_band_y1_px": int(selected_stats.get("y1_px") or root_band_y1_px),
            "selected_band_valid_row_count": int(selected_stats.get("valid_row_count") or 0),
            "tail_width_window_candidates": _candidate_bank_records(),
        }
        selected_step_index = _step_index_for_y0(
            payload["selected_band_y0_px"],
            root_band_y0_px=int(root_band_y0_px),
            candidate_step_px=max(1, int(near_nozzle_band_height_px) // 2),
        )
        payload["selected_band_step_index"] = 0 if selected_step_index is None else int(selected_step_index)
        payload["root_band_step_index"] = 0
        payload.update(sticky_payload)
        return payload

    def _empty_metrics(*, tracked_nozzle_y_px=None):
        root_band_y0_px = None
        root_band_y1_px = None
        if tracked_nozzle_y_px is not None:
            root_band_y0_px = int(
                np.floor(float(tracked_nozzle_y_px) + float(near_nozzle_band_top_px))
            )
            root_band_y1_px = int(root_band_y0_px + int(near_nozzle_band_height_px))
        return {
            "attached_width_px": None,
            "width_valid_row_count": 0,
            "band_y0_px": root_band_y0_px,
            "band_y1_px": root_band_y1_px,
            "attached_width_mode": "root_band",
            "spread_fallback_triggered": False,
            "candidate_window_count": 0,
            "root_band_width_px": None,
            "root_band_width_iqr_px": None,
            "root_band_half_delta_px": None,
            "root_band_y0_px": root_band_y0_px,
            "root_band_y1_px": root_band_y1_px,
            "selected_band_y0_px": root_band_y0_px,
            "selected_band_y1_px": root_band_y1_px,
            "selected_band_step_index": 0,
            "root_band_step_index": 0,
            "tail_width_window_candidates": [],
            "selected_band_valid_row_count": 0,
            **_sticky_fields(
                selected_reason="reset_no_width",
                next_state={},
            ),
        }

    def _window_stats(width_rows: list[dict], *, y0_px: int, y1_px: int) -> dict:
        rows = [
            {"y_px": int(row["y_px"]), "width_px": float(row["width_px"])}
            for row in list(width_rows or [])
            if y0_px <= int(row["y_px"]) < y1_px
        ]
        rows.sort(key=lambda row: int(row["y_px"]))
        valid_row_count = int(len(rows))
        if valid_row_count <= 0:
            return {
                "y0_px": int(y0_px),
                "y1_px": int(y1_px),
                "valid_row_count": 0,
                "median_width_px": None,
                "iqr_px": None,
                "min_width_px": None,
                "max_width_px": None,
                "top_half_median_width_px": None,
                "bottom_half_median_width_px": None,
                "half_delta_px": None,
            }
        widths = np.asarray([float(row["width_px"]) for row in rows], dtype=float)
        split_count = int(max(1, valid_row_count // 2))
        top_widths = widths[:split_count]
        bottom_widths = widths[-split_count:]
        return {
            "y0_px": int(y0_px),
            "y1_px": int(y1_px),
            "valid_row_count": valid_row_count,
            "median_width_px": float(np.median(widths)),
            "iqr_px": float(np.percentile(widths, 75) - np.percentile(widths, 25)),
            "min_width_px": float(np.min(widths)),
            "max_width_px": float(np.max(widths)),
            "top_half_median_width_px": float(np.median(top_widths)),
            "bottom_half_median_width_px": float(np.median(bottom_widths)),
            "half_delta_px": float(abs(np.median(top_widths) - np.median(bottom_widths))),
        }

    tracked_nozzle_y_px = stage3_metric_row.get("tracked_nozzle_y_px")
    if tracked_nozzle_y_px is None:
        return _empty_metrics()

    root_band_y0_px = int(
        np.floor(float(tracked_nozzle_y_px) + float(near_nozzle_band_top_px))
    )
    root_band_y1_px = int(root_band_y0_px + int(near_nozzle_band_height_px))
    width_rows = [
        {"y_px": int(row["y_px"]), "width_px": float(row["width_px"])}
        for row in list(attached_edge_rows or [])
        if row.get("y_px") is not None and row.get("width_px") is not None
    ]
    root_stats = _window_stats(width_rows, y0_px=root_band_y0_px, y1_px=root_band_y1_px)
    root_band_width_px = root_stats.get("median_width_px")
    root_band_width_iqr_px = root_stats.get("iqr_px")
    root_band_half_delta_px = root_stats.get("half_delta_px")
    candidate_step_px = int(max(1, int(near_nozzle_band_height_px) // 2))

    def _candidate_is_eligible(candidate_stats: dict) -> bool:
        candidate_width_px = candidate_stats.get("median_width_px")
        candidate_iqr_px = candidate_stats.get("iqr_px")
        if candidate_width_px is None or candidate_iqr_px is None or root_band_width_px is None:
            return False
        if float(candidate_iqr_px) > max(
            _WIDTH_CANDIDATE_IQR_MIN_PX,
            _WIDTH_CANDIDATE_IQR_FRAC * float(candidate_width_px),
        ):
            return False
        if float(candidate_width_px) > float(root_band_width_px) - max(
            _WIDTH_CANDIDATE_NARROWER_MIN_PX,
            _WIDTH_CANDIDATE_NARROWER_FRAC * float(root_band_width_px),
        ):
            return False
        return True

    candidate_window_count = 0
    candidate_stats_by_step = {
        0: dict(root_stats),
    }
    candidate_stats_by_y0 = {
        int(root_band_y0_px): dict(root_stats),
    }
    candidate_eligible_by_step = {}
    eligible_by_y0 = {}
    eligible_candidates = []
    max_candidate_start_px = int(root_band_y0_px + int(_WIDTH_MAX_CANDIDATE_START_DELTA_PX))
    for candidate_y0_px in range(
        int(root_band_y0_px) + int(candidate_step_px),
        int(max_candidate_start_px) + 1,
        int(candidate_step_px),
    ):
        candidate_y1_px = int(candidate_y0_px + int(near_nozzle_band_height_px))
        candidate_stats = _window_stats(
            width_rows,
            y0_px=int(candidate_y0_px),
            y1_px=int(candidate_y1_px),
        )
        candidate_window_count += 1
        candidate_step_index = _step_index_for_y0(
            candidate_stats.get("y0_px"),
            root_band_y0_px=int(root_band_y0_px),
            candidate_step_px=int(candidate_step_px),
        )
        if candidate_step_index is not None:
            candidate_stats_by_step[int(candidate_step_index)] = dict(candidate_stats)
        candidate_stats_by_y0[int(candidate_stats["y0_px"])] = dict(candidate_stats)
        candidate_eligible = bool(
            int(candidate_stats.get("valid_row_count") or 0) >= int(min_band_valid_rows)
            and _candidate_is_eligible(candidate_stats)
        )
        if candidate_step_index is not None:
            candidate_eligible_by_step[int(candidate_step_index)] = bool(candidate_eligible)
        if candidate_eligible:
            eligible = dict(candidate_stats)
            eligible_by_y0[int(eligible["y0_px"])] = eligible
            eligible_candidates.append(eligible)

    def _candidate_bank_records() -> list[dict]:
        if not bool(window_bank_enabled):
            return []
        records = []
        for step_index in sorted(candidate_stats_by_step):
            stats = dict(candidate_stats_by_step.get(int(step_index)) or {})
            width_px = _to_float_or_none(stats.get("median_width_px"))
            valid_rows = int(stats.get("valid_row_count") or 0)
            width_usable = bool(width_px is not None and valid_rows >= int(min_band_valid_rows))
            eligible_as_selected = bool(width_usable) if int(step_index) == 0 else bool(
                candidate_eligible_by_step.get(int(step_index), False)
            )
            records.append(
                {
                    "step_index": int(step_index),
                    "mode": _mode_for_step(int(step_index)),
                    "y0_px": _to_int_or_none(stats.get("y0_px")),
                    "y1_px": _to_int_or_none(stats.get("y1_px")),
                    "median_width_px": width_px,
                    "iqr_px": _to_float_or_none(stats.get("iqr_px")),
                    "half_delta_px": _to_float_or_none(stats.get("half_delta_px")),
                    "valid_row_count": int(valid_rows),
                    "width_usable": bool(width_usable),
                    "eligible_as_selected_window": bool(eligible_as_selected),
                }
            )
        return records

    def _stats_for_step(step_index: int | None) -> dict | None:
        if step_index is None:
            return None
        stats = candidate_stats_by_step.get(int(step_index))
        if stats is None:
            return None
        if int(stats.get("valid_row_count") or 0) < int(min_band_valid_rows):
            return None
        return dict(stats)

    def _unavailable_metrics(
        *,
        selected_reason: str,
        locked_reused: bool = False,
        locked_invalid: bool = False,
        monotonic_lower_bound_step_index: int | None = None,
        monotonic_upper_bound_step_index: int | None = None,
        monotonic_upward_move_blocked: bool = False,
    ) -> dict:
        metrics = _empty_metrics(tracked_nozzle_y_px=tracked_nozzle_y_px)
        metrics.update(
            {
                "width_valid_row_count": 0,
                "selected_band_valid_row_count": 0,
                "candidate_window_count": int(candidate_window_count),
                "tail_width_window_candidates": _candidate_bank_records(),
                "root_band_width_px": root_band_width_px,
                "root_band_width_iqr_px": root_band_width_iqr_px,
                "root_band_half_delta_px": root_band_half_delta_px,
                **_sticky_fields(
                    selected_reason=selected_reason,
                    next_state=dict(sticky_state),
                    locked_reused=locked_reused,
                    locked_invalid=locked_invalid,
                    monotonic_lower_bound_step_index=monotonic_lower_bound_step_index,
                    monotonic_upper_bound_step_index=monotonic_upper_bound_step_index,
                    monotonic_upward_move_blocked=monotonic_upward_move_blocked,
                ),
            }
        )
        return metrics

    def _payload_for_step(
        *,
        stats: dict,
        step_index: int,
        selected_reason: str,
        spread_fallback_triggered: bool,
        instant_stats: dict | None = None,
        locked_reused: bool = False,
        locked_invalid: bool = False,
        monotonic_lower_bound_step_index: int | None = None,
        monotonic_upper_bound_step_index: int | None = None,
        monotonic_upward_move_blocked: bool = False,
    ) -> dict:
        mode = _mode_for_step(step_index)
        next_state = _state_for_selected(
            stats,
            step_index=int(step_index),
            attached_width_mode=mode,
        )
        return _metrics_payload(
            selected_stats=stats,
            attached_width_mode=mode,
            spread_fallback_triggered=bool(spread_fallback_triggered),
            candidate_window_count=candidate_window_count,
            root_band_width_px=root_band_width_px,
            root_band_width_iqr_px=root_band_width_iqr_px,
            root_band_half_delta_px=root_band_half_delta_px,
            root_band_y0_px=root_band_y0_px,
            root_band_y1_px=root_band_y1_px,
            sticky_payload=_sticky_fields(
                selected_reason=selected_reason,
                instant_stats=instant_stats,
                next_state=next_state,
                locked_reused=locked_reused,
                locked_invalid=locked_invalid,
                monotonic_lower_bound_step_index=monotonic_lower_bound_step_index,
                monotonic_upper_bound_step_index=monotonic_upper_bound_step_index,
                monotonic_upward_move_blocked=monotonic_upward_move_blocked,
            ),
        )

    lower_bound_step, upper_bound_step = _monotonic_bounds(
        delay_value_us=current_delay_from_emergence_us
    )

    if locked_step_index is not None:
        locked_stats = _stats_for_step(locked_step_index)
        if locked_stats is None:
            return _unavailable_metrics(
                selected_reason="delay_locked_window_invalid",
                locked_reused=True,
                locked_invalid=True,
                monotonic_lower_bound_step_index=lower_bound_step,
                monotonic_upper_bound_step_index=upper_bound_step,
            )
        return _payload_for_step(
            stats=locked_stats,
            step_index=int(locked_step_index),
            selected_reason="delay_locked_window_reused",
            spread_fallback_triggered=int(locked_step_index) > 0,
            locked_reused=True,
            monotonic_lower_bound_step_index=lower_bound_step,
            monotonic_upper_bound_step_index=upper_bound_step,
        )

    if int(root_stats.get("valid_row_count") or 0) < int(min_band_valid_rows):
        return _unavailable_metrics(
            selected_reason="reset_insufficient_root_rows",
            monotonic_lower_bound_step_index=lower_bound_step,
            monotonic_upper_bound_step_index=upper_bound_step,
        )

    root_clearly_uneven = bool(
        root_band_width_px is not None
        and root_band_width_iqr_px is not None
        and root_band_half_delta_px is not None
        and float(root_band_width_iqr_px)
        >= max(_WIDTH_ROOT_IQR_MIN_PX, _WIDTH_ROOT_IQR_FRAC * float(root_band_width_px))
        and float(root_band_half_delta_px)
        >= max(
            _WIDTH_ROOT_HALF_DELTA_MIN_PX,
            _WIDTH_ROOT_HALF_DELTA_FRAC * float(root_band_width_px),
        )
    )
    instant_stats = dict(eligible_candidates[0]) if (root_clearly_uneven and eligible_candidates) else None
    if not root_clearly_uneven:
        if lower_bound_step is not None and int(lower_bound_step) > 0:
            bound_stats = _stats_for_step(lower_bound_step)
            if bound_stats is None:
                return _unavailable_metrics(
                    selected_reason="monotonic_lower_window_invalid",
                    monotonic_lower_bound_step_index=lower_bound_step,
                    monotonic_upper_bound_step_index=upper_bound_step,
                    monotonic_upward_move_blocked=True,
                )
            return _payload_for_step(
                stats=bound_stats,
                step_index=int(lower_bound_step),
                selected_reason="monotonic_hold_lower_window",
                spread_fallback_triggered=True,
                monotonic_lower_bound_step_index=lower_bound_step,
                monotonic_upper_bound_step_index=upper_bound_step,
                monotonic_upward_move_blocked=True,
            )
        return _metrics_payload(
            selected_stats=dict(root_stats),
            attached_width_mode="root_band",
            spread_fallback_triggered=False,
            candidate_window_count=0,
            root_band_width_px=root_band_width_px,
            root_band_width_iqr_px=root_band_width_iqr_px,
            root_band_half_delta_px=root_band_half_delta_px,
            root_band_y0_px=root_band_y0_px,
            root_band_y1_px=root_band_y1_px,
            sticky_payload=_sticky_fields(
                selected_reason="reset_root_band",
                next_state=(
                    _state_for_selected(
                        dict(root_stats),
                        step_index=0,
                        attached_width_mode="root_band",
                    )
                    if current_delay_from_emergence_us is not None
                    else {}
                ),
                monotonic_lower_bound_step_index=lower_bound_step,
                monotonic_upper_bound_step_index=upper_bound_step,
            ),
        )
    if instant_stats is None:
        if lower_bound_step is not None and int(lower_bound_step) > 0:
            bound_stats = _stats_for_step(lower_bound_step)
            if bound_stats is None:
                return _unavailable_metrics(
                    selected_reason="monotonic_lower_window_invalid",
                    monotonic_lower_bound_step_index=lower_bound_step,
                    monotonic_upper_bound_step_index=upper_bound_step,
                    monotonic_upward_move_blocked=True,
                )
            return _payload_for_step(
                stats=bound_stats,
                step_index=int(lower_bound_step),
                selected_reason="monotonic_hold_lower_window",
                spread_fallback_triggered=True,
                monotonic_lower_bound_step_index=lower_bound_step,
                monotonic_upper_bound_step_index=upper_bound_step,
                monotonic_upward_move_blocked=True,
            )
        return _metrics_payload(
            selected_stats=dict(root_stats),
            attached_width_mode="root_band",
            spread_fallback_triggered=False,
            candidate_window_count=candidate_window_count,
            root_band_width_px=root_band_width_px,
            root_band_width_iqr_px=root_band_width_iqr_px,
            root_band_half_delta_px=root_band_half_delta_px,
            root_band_y0_px=root_band_y0_px,
            root_band_y1_px=root_band_y1_px,
            sticky_payload=_sticky_fields(
                selected_reason="reset_no_lower_candidate",
                next_state=(
                    _state_for_selected(
                        dict(root_stats),
                        step_index=0,
                        attached_width_mode="root_band",
                    )
                    if current_delay_from_emergence_us is not None
                    else {}
                ),
                monotonic_lower_bound_step_index=lower_bound_step,
                monotonic_upper_bound_step_index=upper_bound_step,
            ),
        )

    selected_stats = dict(instant_stats)
    attached_width_mode = "lower_consistent_window"
    spread_fallback_triggered = True
    sticky_reason = "instant_candidate"
    sticky_blocked = False
    sticky_streak = 0
    next_state = _state_for_selected(
        selected_stats,
        step_index=_step_index_for_y0(
            selected_stats.get("y0_px"),
            root_band_y0_px=root_band_y0_px,
            candidate_step_px=candidate_step_px,
        ),
        attached_width_mode=attached_width_mode,
    )

    if sticky_active:
        previous_stats = None
        if previous_y0_px is not None:
            maybe_previous_stats = candidate_stats_by_y0.get(int(previous_y0_px))
            if maybe_previous_stats is not None and _candidate_is_eligible(maybe_previous_stats):
                previous_stats = dict(maybe_previous_stats)

        if previous_stats is None:
            sticky_reason = "sticky_initial_candidate" if previous_y0_px is None else "sticky_previous_invalid"
            next_state = _state_for_selected(selected_stats)
        else:
            previous_width_px = _to_float_or_none(previous_stats.get("median_width_px"))
            switch_drop_px = max(
                float(sticky_window_min_switch_drop_px),
                float(sticky_window_min_switch_drop_frac) * float(previous_width_px or 0.0),
            )
            material_stats = None
            if previous_width_px is not None:
                for candidate in eligible_candidates:
                    candidate_y0_px = int(candidate["y0_px"])
                    if candidate_y0_px <= int(previous_y0_px):
                        continue
                    candidate_width_px = _to_float_or_none(candidate.get("median_width_px"))
                    if candidate_width_px is None:
                        continue
                    if float(candidate_width_px) <= float(previous_width_px) - float(switch_drop_px):
                        material_stats = dict(candidate)
                        break

            preferred_stats = dict(material_stats or instant_stats)
            preferred_y0_px = int(preferred_stats["y0_px"])
            previous_selected_y0_px = int(previous_stats["y0_px"])
            if preferred_y0_px == previous_selected_y0_px:
                selected_stats = dict(previous_stats)
                sticky_reason = "sticky_same_window"
                next_state = _state_for_selected(
                    selected_stats,
                    step_index=_step_index_for_y0(
                        selected_stats.get("y0_px"),
                        root_band_y0_px=root_band_y0_px,
                        candidate_step_px=candidate_step_px,
                    ),
                    attached_width_mode=attached_width_mode,
                )
            else:
                pending_y0_px = _to_int_or_none(sticky_state.get("pending_candidate_y0_px"))
                if pending_y0_px == preferred_y0_px:
                    sticky_streak = int(sticky_state.get("candidate_streak") or 0) + 1
                else:
                    sticky_streak = 1

                confirmed = bool(
                    int(max(1, sticky_window_confirm_frames)) <= 1
                    or int(sticky_streak) >= int(max(1, sticky_window_confirm_frames))
                )
                material_switch = material_stats is not None
                if material_switch or confirmed:
                    max_step_px = int(max(1, sticky_window_max_step_multiplier)) * int(candidate_step_px)
                    target_stats = dict(preferred_stats)
                    target_y0_px = int(target_stats["y0_px"])
                    if abs(int(target_y0_px) - int(previous_selected_y0_px)) > int(max_step_px):
                        direction = 1 if int(target_y0_px) > int(previous_selected_y0_px) else -1
                        step_y0_px = int(previous_selected_y0_px) + int(direction * max_step_px)
                        step_stats = eligible_by_y0.get(int(step_y0_px))
                        if step_stats is None:
                            selected_stats = dict(previous_stats)
                            sticky_reason = "sticky_hold_step_candidate_unavailable"
                            sticky_blocked = True
                            next_state = _state_for_selected(
                                selected_stats,
                                step_index=_step_index_for_y0(
                                    selected_stats.get("y0_px"),
                                    root_band_y0_px=root_band_y0_px,
                                    candidate_step_px=candidate_step_px,
                                ),
                                attached_width_mode=attached_width_mode,
                                pending_stats=preferred_stats,
                                candidate_streak=sticky_streak,
                            )
                        else:
                            selected_stats = dict(step_stats)
                            sticky_reason = (
                                "sticky_step_toward_material_candidate"
                                if material_switch
                                else "sticky_step_toward_confirmed_candidate"
                            )
                            next_state = _state_for_selected(
                                selected_stats,
                                step_index=_step_index_for_y0(
                                    selected_stats.get("y0_px"),
                                    root_band_y0_px=root_band_y0_px,
                                    candidate_step_px=candidate_step_px,
                                ),
                                attached_width_mode=attached_width_mode,
                                pending_stats=preferred_stats,
                                candidate_streak=sticky_streak,
                            )
                    else:
                        selected_stats = dict(target_stats)
                        sticky_reason = (
                            "sticky_material_candidate"
                            if material_switch
                            else "sticky_confirmed_candidate"
                        )
                        next_state = _state_for_selected(
                            selected_stats,
                            step_index=_step_index_for_y0(
                                selected_stats.get("y0_px"),
                                root_band_y0_px=root_band_y0_px,
                                candidate_step_px=candidate_step_px,
                            ),
                            attached_width_mode=attached_width_mode,
                        )
                else:
                    selected_stats = dict(previous_stats)
                    sticky_reason = "sticky_hold_previous"
                    sticky_blocked = True
                    next_state = _state_for_selected(
                        selected_stats,
                        step_index=_step_index_for_y0(
                            selected_stats.get("y0_px"),
                            root_band_y0_px=root_band_y0_px,
                            candidate_step_px=candidate_step_px,
                        ),
                        attached_width_mode=attached_width_mode,
                        pending_stats=preferred_stats,
                        candidate_streak=sticky_streak,
                    )

    selected_step_index = _step_index_for_y0(
        selected_stats.get("y0_px"),
        root_band_y0_px=root_band_y0_px,
        candidate_step_px=candidate_step_px,
    )
    if selected_step_index is None:
        selected_step_index = 0
    monotonic_upward_move_blocked = False
    if lower_bound_step is not None and int(selected_step_index) < int(lower_bound_step):
        bound_stats = _stats_for_step(lower_bound_step)
        if bound_stats is None:
            return _unavailable_metrics(
                selected_reason="monotonic_lower_window_invalid",
                monotonic_lower_bound_step_index=lower_bound_step,
                monotonic_upper_bound_step_index=upper_bound_step,
                monotonic_upward_move_blocked=True,
            )
        selected_stats = dict(bound_stats)
        selected_step_index = int(lower_bound_step)
        attached_width_mode = _mode_for_step(selected_step_index)
        spread_fallback_triggered = selected_step_index > 0
        sticky_reason = "monotonic_hold_lower_window"
        sticky_blocked = True
        monotonic_upward_move_blocked = True
    if upper_bound_step is not None and int(selected_step_index) > int(upper_bound_step):
        bound_stats = _stats_for_step(upper_bound_step)
        if bound_stats is None:
            return _unavailable_metrics(
                selected_reason="monotonic_upper_window_invalid",
                monotonic_lower_bound_step_index=lower_bound_step,
                monotonic_upper_bound_step_index=upper_bound_step,
            )
        selected_stats = dict(bound_stats)
        selected_step_index = int(upper_bound_step)
        attached_width_mode = _mode_for_step(selected_step_index)
        spread_fallback_triggered = selected_step_index > 0
        sticky_reason = "monotonic_cap_to_future_window"
        sticky_blocked = True
    if not (
        sticky_blocked
        and sticky_reason
        in {
            "sticky_hold_previous",
            "sticky_candidate_pending",
            "sticky_confirm_wait",
        }
        and isinstance(next_state, dict)
        and "pending_candidate_y0_px" in next_state
    ):
        next_state = _state_for_selected(
            selected_stats,
            step_index=int(selected_step_index),
            attached_width_mode=attached_width_mode,
        )

    return _metrics_payload(
        selected_stats=selected_stats,
        attached_width_mode=attached_width_mode,
        spread_fallback_triggered=spread_fallback_triggered,
        candidate_window_count=candidate_window_count,
        root_band_width_px=root_band_width_px,
        root_band_width_iqr_px=root_band_width_iqr_px,
        root_band_half_delta_px=root_band_half_delta_px,
        root_band_y0_px=root_band_y0_px,
        root_band_y1_px=root_band_y1_px,
        sticky_payload=_sticky_fields(
            selected_reason=sticky_reason,
            instant_stats=instant_stats,
            next_state=next_state,
            candidate_streak=sticky_streak,
            switch_blocked=sticky_blocked,
            monotonic_lower_bound_step_index=lower_bound_step,
            monotonic_upper_bound_step_index=upper_bound_step,
            monotonic_upward_move_blocked=monotonic_upward_move_blocked,
        ),
    )


def _attached_component_clearance(stage3_metric_row: dict, attached_component_row: dict | None):
    if not attached_component_row:
        return None
    roi_y1 = stage3_metric_row.get("roi_y1")
    last_valid_y_px = attached_component_row.get("last_valid_y_px")
    if roi_y1 is None or last_valid_y_px is None:
        return None
    return int(int(roi_y1) - 1 - int(last_valid_y_px))


def _attached_component_extension_below_band(
    attached_component_row: dict | None,
    *,
    band_y1_px,
):
    if not attached_component_row or band_y1_px is None:
        return None
    last_valid_y_px = attached_component_row.get("last_valid_y_px")
    if last_valid_y_px is None:
        return None
    return int(int(last_valid_y_px) - int(band_y1_px) + 1)


def _attached_near_nozzle_breakup(
    stage3_metric_row: dict,
    attached_component_row: dict | None,
    width_metrics: dict,
    *,
    config: dict,
):
    roi_height = stage3_metric_row.get("roi_height")
    min_extension_px = int(config["near_nozzle_band_height_px"])
    if roi_height not in (None, ""):
        try:
            min_extension_px = max(
                int(config["near_nozzle_band_height_px"]),
                int(
                    round(
                        float(roi_height)
                        * float(config["attached_breakup_min_extension_roi_frac"])
                    )
                ),
            )
        except Exception:
            min_extension_px = int(config["near_nozzle_band_height_px"])

    detached_component_count = int(
        stage3_metric_row.get("accepted_detached_component_count") or 0
    )
    extension_px = _attached_component_extension_below_band(
        attached_component_row,
        band_y1_px=width_metrics.get("root_band_y1_px", width_metrics.get("band_y1_px")),
    )
    detected = bool(
        extension_px is not None
        and detached_component_count
        >= int(config["attached_breakup_min_detached_components"])
        and int(extension_px) < int(min_extension_px)
    )
    return {
        "attached_near_nozzle_breakup_detected": bool(detected),
        "attached_band_extension_px": extension_px,
        "attached_breakup_min_extension_px": int(min_extension_px),
    }


def _residue_stub_with_detached_continuation(
    attached_component_row: dict | None,
    component_rows: list[dict],
    accepted_components: list[dict],
    breakup_metrics: dict,
    *,
    config: dict,
):
    default = {
        "residue_stub_with_detached_continuation": False,
        "detached_continuation_component_id": None,
        "detached_continuation_gap_px": None,
        "detached_continuation_height_px": None,
        "detached_continuation_row_count": None,
    }
    if not attached_component_row:
        return default

    detached_rows = sorted(
        (
            dict(row)
            for row in list(component_rows or [])
            if str(row.get("component_role") or "") == "detached_accepted"
        ),
        key=lambda row: (
            int(row.get("top_y_px") or 0),
            int(row.get("last_valid_y_px") or 0),
        ),
    )
    if not detached_rows:
        return default

    detached_row = detached_rows[0]
    detached_component_id = str(detached_row.get("component_id") or "").strip() or None
    component_by_id = {
        str(component.get("component_id") or "").strip(): dict(component)
        for component in list(accepted_components or [])
        if str(component.get("component_id") or "").strip()
    }
    detached_component = None if detached_component_id is None else component_by_id.get(detached_component_id)
    detached_row_count = len(list((detached_component or {}).get("edge_rows") or []))

    attached_last_valid_y_px = attached_component_row.get("last_valid_y_px")
    detached_top_y_px = detached_row.get("top_y_px")
    detached_last_valid_y_px = detached_row.get("last_valid_y_px")
    gap_px = None
    if attached_last_valid_y_px not in (None, "") and detached_top_y_px not in (None, ""):
        gap_px = int(int(detached_top_y_px) - int(attached_last_valid_y_px) - 1)
    height_px = None
    if detached_top_y_px not in (None, "") and detached_last_valid_y_px not in (None, ""):
        height_px = int(int(detached_last_valid_y_px) - int(detached_top_y_px) + 1)

    extension_px = breakup_metrics.get("attached_band_extension_px")
    min_extension_px = breakup_metrics.get("attached_breakup_min_extension_px")
    short_attached_stub = bool(
        extension_px is not None
        and min_extension_px is not None
        and int(extension_px) < int(min_extension_px)
    )
    min_gap_px = max(8, int(config["near_nozzle_band_height_px"]) // 4)
    min_detached_row_count = max(
        int(config["min_band_valid_rows"]),
        int(config["near_nozzle_band_height_px"]),
    )
    detected = bool(
        short_attached_stub
        and gap_px is not None
        and int(gap_px) >= int(min_gap_px)
        and int(detached_row_count) >= int(min_detached_row_count)
    )
    return {
        "residue_stub_with_detached_continuation": bool(detected),
        "detached_continuation_component_id": detached_component_id,
        "detached_continuation_gap_px": gap_px,
        "detached_continuation_height_px": height_px,
        "detached_continuation_row_count": int(detached_row_count),
    }


def _visible_fluid_clearance_px(
    *,
    frame_metric_row: dict,
    attached_bottom_clearance_px,
):
    try:
        clearance_px = frame_metric_row.get("min_accepted_fluid_distance_from_bottom_px")
    except Exception:
        clearance_px = None
    if clearance_px in (None, ""):
        clearance_px = attached_bottom_clearance_px
    try:
        if clearance_px in (None, ""):
            return None
        return float(clearance_px)
    except Exception:
        return None


def _detached_near_bottom_warning(stage3_metric_row: dict, component_rows: list[dict], *, threshold_px: int):
    roi_y1 = stage3_metric_row.get("roi_y1")
    if roi_y1 is None:
        return False
    for row in list(component_rows or []):
        if str(row.get("component_role") or "") != "detached_accepted":
            continue
        last_valid_y_px = row.get("last_valid_y_px")
        if last_valid_y_px is None:
            continue
        distance_from_bottom_px = int(int(roi_y1) - 1 - int(last_valid_y_px))
        if distance_from_bottom_px <= int(threshold_px):
            return True
    return False


def _near_nozzle_detached_warning(
    stage3_metric_row: dict,
    component_rows: list[dict],
    *,
    near_nozzle_band_top_px: int,
    near_nozzle_band_height_px: int,
):
    cutoff_y_px = stage3_metric_row.get("cutoff_y_px")
    if cutoff_y_px is None:
        return False
    band_y0_px = int(int(cutoff_y_px) + int(near_nozzle_band_top_px))
    band_y1_px = int(band_y0_px + int(near_nozzle_band_height_px))
    for row in list(component_rows or []):
        if str(row.get("component_role") or "") != "detached_accepted":
            continue
        top_y_px = row.get("top_y_px")
        if top_y_px is None:
            continue
        top_y_px = int(top_y_px)
        if band_y0_px <= int(top_y_px) < band_y1_px:
            return True
    return False


def _component_volume_map(component_volume_rows: list[dict]) -> dict[str, dict]:
    volume_map = {}
    for row in list(component_volume_rows or []):
        component_id = str(row.get("component_id") or "").strip()
        if not component_id:
            continue
        volume_map[component_id] = dict(row)
    return volume_map


def _fit_centerline(edge_rows: list[dict]) -> tuple[float, float] | None:
    rows = [dict(row or {}) for row in list(edge_rows or [])]
    if len(rows) < 2:
        return None
    y_values = np.asarray([float(row["y_px"]) for row in rows], dtype=float)
    x_values = np.asarray([float(row["center_x_px"]) for row in rows], dtype=float)
    if np.any(~np.isfinite(y_values)) or np.any(~np.isfinite(x_values)):
        return None
    design = np.column_stack((y_values, np.ones_like(y_values)))
    try:
        slope, intercept = np.linalg.lstsq(design, x_values, rcond=None)[0]
    except Exception:
        return None
    if not np.isfinite(slope) or not np.isfinite(intercept):
        return None
    return float(slope), float(intercept)


def _centerline_residual_metrics(
    edge_rows: list[dict],
    *,
    lower_fraction: float | None = None,
) -> dict:
    rows = [dict(row or {}) for row in list(edge_rows or [])]
    rows.sort(key=lambda row: int(row["y_px"]))
    if lower_fraction is not None and rows:
        fraction = float(max(0.0, min(1.0, lower_fraction)))
        keep_count = int(max(1, np.ceil(float(len(rows)) * fraction)))
        rows = rows[-keep_count:]
    fit = _fit_centerline(rows)
    if fit is None:
        return {
            "row_count": int(len(rows)),
            "span_px": None,
            "rms_px": None,
            "slope_px_per_row": None,
            "intercept_px": None,
        }
    slope_px_per_row, intercept_px = fit
    residuals = np.asarray(
        [
            float(row["center_x_px"]) - ((float(slope_px_per_row) * float(row["y_px"])) + float(intercept_px))
            for row in rows
        ],
        dtype=float,
    )
    if residuals.size <= 0 or np.any(~np.isfinite(residuals)):
        span_px = None
        rms_px = None
    else:
        span_px = float(np.max(residuals) - np.min(residuals))
        rms_px = float(np.sqrt(np.mean(residuals**2)))
    return {
        "row_count": int(len(rows)),
        "span_px": span_px,
        "rms_px": rms_px,
        "slope_px_per_row": float(slope_px_per_row),
        "intercept_px": float(intercept_px),
    }


def _confidence_smaller_better(value, *, full_at, zero_at) -> float | None:
    if value is None:
        return None
    value = float(value)
    full_at = float(full_at)
    zero_at = float(zero_at)
    if value <= full_at:
        return 1.0
    if value >= zero_at:
        return 0.0
    span = float(zero_at - full_at)
    if span <= 0.0:
        return 0.0
    return float(max(0.0, min(1.0, 1.0 - ((value - full_at) / span))))


def _confidence_larger_better(value, *, full_at, zero_at) -> float | None:
    if value is None:
        return None
    value = float(value)
    full_at = float(full_at)
    zero_at = float(zero_at)
    if value >= full_at:
        return 1.0
    if value <= zero_at:
        return 0.0
    span = float(full_at - zero_at)
    if span <= 0.0:
        return 0.0
    return float(max(0.0, min(1.0, (value - zero_at) / span)))


def _min_confidence(*values) -> float | None:
    clean = []
    for value in values:
        if value is None:
            continue
        clean.append(float(max(0.0, min(1.0, float(value)))))
    if not clean:
        return None
    return float(min(clean))


def _lower_rows(edge_rows: list[dict], *, lower_fraction: float) -> list[dict]:
    rows = [dict(row or {}) for row in list(edge_rows or [])]
    rows.sort(key=lambda row: int(row["y_px"]))
    if not rows:
        return []
    fraction = float(max(0.0, min(1.0, lower_fraction)))
    keep_count = int(max(1, np.ceil(float(len(rows)) * fraction)))
    return rows[-keep_count:]


def _fit_residual_rms(rows: list[dict], *, x_key: str) -> float | None:
    if len(rows) < 2:
        return None
    y_values = np.asarray([float(row["y_px"]) for row in rows], dtype=float)
    x_values = np.asarray([float(row[x_key]) for row in rows], dtype=float)
    if np.any(~np.isfinite(y_values)) or np.any(~np.isfinite(x_values)):
        return None
    design = np.column_stack((y_values, np.ones_like(y_values)))
    try:
        slope, intercept = np.linalg.lstsq(design, x_values, rcond=None)[0]
    except Exception:
        return None
    predicted = (float(slope) * y_values) + float(intercept)
    residuals = x_values - predicted
    if residuals.size <= 0 or np.any(~np.isfinite(residuals)):
        return None
    return float(np.sqrt(np.mean(residuals**2)))


def _axis_symmetry_score(
    *,
    final_mask,
    roi: dict,
    slope_px_per_row: float,
    intercept_px: float,
) -> float | None:
    if final_mask is None:
        return None
    mask = np.asarray(final_mask)
    if mask.ndim != 2 or mask.size <= 0:
        return None
    fg_mask = mask > 0
    if not np.any(fg_mask):
        return None

    roi_x0 = int(roi.get("x0", 0) or 0)
    roi_y0 = int(roi.get("y0", 0) or 0)
    matched = 0
    total = 0
    occupied_rows = np.flatnonzero(np.any(fg_mask, axis=1))
    for y_local in occupied_rows.tolist():
        x_indices = np.flatnonzero(fg_mask[y_local])
        if x_indices.size <= 0:
            continue
        y_global = int(roi_y0 + int(y_local))
        x_fit_global = (float(slope_px_per_row) * float(y_global)) + float(intercept_px)
        x_fit_local = float(x_fit_global) - float(roi_x0)
        total += int(x_indices.size)
        reflected = np.rint((2.0 * float(x_fit_local)) - x_indices.astype(float)).astype(int)
        valid = (reflected >= 0) & (reflected < fg_mask.shape[1])
        if np.any(valid):
            matched += int(np.count_nonzero(fg_mask[y_local, reflected[valid]]))
    if total <= 0:
        return None
    return float(matched / float(total))


def _attached_geometry_summary(
    attached_edge_rows: list[dict],
    *,
    lower_row_fraction: float,
    min_rows: int,
    span_max_px: float,
    config: dict | None = None,
    geometry_assessable: bool,
) -> dict:
    config = _resolved_analysis_config(config)
    warn_span_px = float(config.get("attached_lower_centerline_span_warn_px", span_max_px))
    reject_span_px = float(config.get("attached_lower_centerline_span_reject_px", span_max_px))
    metrics = _centerline_residual_metrics(
        attached_edge_rows,
        lower_fraction=float(lower_row_fraction),
    )
    row_count = int(metrics.get("row_count") or 0)
    span_px = metrics.get("span_px")
    rms_px = metrics.get("rms_px")
    reasons = []
    warnings = []
    geometry_ok = None
    if geometry_assessable:
        if row_count >= int(min_rows) and span_px is not None:
            if float(span_px) > float(reject_span_px):
                geometry_ok = False
                reasons.append("attached_lower_centerline_span_high")
            else:
                geometry_ok = True
                if float(span_px) > float(warn_span_px):
                    warnings.append("attached_lower_centerline_span_high")
    geometry_confidence = None
    if geometry_assessable:
        geometry_confidence = _confidence_smaller_better(
            span_px,
            full_at=float(config.get("attached_geometry_confidence_full_span_px", 25)),
            zero_at=float(config.get("attached_geometry_confidence_zero_span_px", reject_span_px)),
        )
    return {
        "attached_lower_centerline_span_px": span_px,
        "attached_lower_centerline_rms_px": rms_px,
        "attached_volume_geometry_ok": geometry_ok,
        "attached_geometry_confidence": geometry_confidence,
        "attached_geometry_reasons": reasons,
        "attached_geometry_warnings": warnings,
        "attached_lower_centerline_row_count": row_count,
    }


def _detached_component_geometry_details(
    *,
    detached_component: dict,
    component_volume_nl,
    detached_visible_volume_nl,
    roi: dict,
    tracked_nozzle_x_px,
    config: dict,
) -> dict:
    component_id = str(detached_component.get("component_id") or "")
    volume_nl = None if component_volume_nl is None else float(component_volume_nl)
    detached_total_nl = None if detached_visible_volume_nl is None else float(detached_visible_volume_nl)
    material_min_nl = float(config["detached_material_volume_min_nl"])
    material_fraction_min = float(config["detached_material_volume_fraction_min"])
    material_component = bool(
        volume_nl is not None
        and (
            float(volume_nl) >= float(material_min_nl)
            or (
                detached_total_nl not in (None, 0.0)
                and float(volume_nl) >= (float(material_fraction_min) * float(detached_total_nl))
            )
        )
    )
    if not material_component:
        return {
            "component_id": component_id,
            "component_volume_nl": volume_nl,
            "local_centerline_span_px": None,
            "axis_symmetry_score": None,
            "axis_offset_px": None,
            "geometry_confidence": None,
            "geometry_ok": True,
            "geometry_reasons": [],
        }

    edge_rows = [dict(row or {}) for row in list(detached_component.get("edge_rows") or [])]
    metrics = _centerline_residual_metrics(edge_rows, lower_fraction=None)
    span_px = metrics.get("span_px")
    fit_available = (
        metrics.get("slope_px_per_row") is not None and metrics.get("intercept_px") is not None
    )
    symmetry_score = None
    if fit_available:
        symmetry_score = _axis_symmetry_score(
            final_mask=detached_component.get("final_mask"),
            roi=roi,
            slope_px_per_row=float(metrics["slope_px_per_row"]),
            intercept_px=float(metrics["intercept_px"]),
        )

    axis_offset_px = None
    if tracked_nozzle_x_px is not None and detached_component.get("anchor_center_x_px") is not None:
        axis_offset_px = float(
            abs(float(detached_component["anchor_center_x_px"]) - float(tracked_nozzle_x_px))
        )

    reasons = []
    if symmetry_score is None or float(symmetry_score) < float(config["detached_axis_symmetry_min"]):
        reasons.append("detached_axis_symmetry_low")
    if span_px is None or float(span_px) > float(config["detached_local_centerline_span_max_px"]):
        reasons.append("detached_local_centerline_span_high")
    if reasons and axis_offset_px is not None and float(axis_offset_px) > float(config["detached_axis_offset_warn_px"]):
        reasons.append("detached_axis_offset_high")
    geometry_confidence = _min_confidence(
        _confidence_larger_better(
            symmetry_score,
            full_at=float(config["detached_geometry_confidence_full_symmetry"]),
            zero_at=float(config["detached_geometry_confidence_zero_symmetry"]),
        ),
        _confidence_smaller_better(
            span_px,
            full_at=float(config["detached_geometry_confidence_full_span_px"]),
            zero_at=float(config["detached_geometry_confidence_zero_span_px"]),
        ),
    )

    return {
        "component_id": component_id,
        "component_volume_nl": volume_nl,
        "local_centerline_span_px": None if span_px is None else float(span_px),
        "axis_symmetry_score": None if symmetry_score is None else float(symmetry_score),
        "axis_offset_px": None if axis_offset_px is None else float(axis_offset_px),
        "geometry_confidence": geometry_confidence,
        "geometry_ok": bool(not reasons),
        "geometry_reasons": reasons,
    }


def _detached_geometry_summary(
    *,
    accepted_components: list[dict],
    component_volume_rows: list[dict],
    detached_visible_volume_nl,
    roi: dict,
    tracked_nozzle_x_px,
    config: dict,
    geometry_assessable: bool,
) -> dict:
    if not geometry_assessable:
        return {
            "detached_volume_geometry_ok": None,
            "detached_geometry_details": [],
            "min_detached_axis_symmetry_score": None,
            "max_detached_local_centerline_span_px": None,
            "max_detached_axis_offset_px": None,
            "detached_geometry_confidence": None,
            "detached_geometry_reasons": [],
        }

    volume_map = _component_volume_map(component_volume_rows)
    details = []
    for component in list(accepted_components or []):
        if str(component.get("component_role") or "") != "detached_accepted":
            continue
        component_id = str(component.get("component_id") or "").strip()
        component_volume_row = volume_map.get(component_id, {})
        details.append(
            _detached_component_geometry_details(
                detached_component=dict(component),
                component_volume_nl=component_volume_row.get("component_volume_nl"),
                detached_visible_volume_nl=detached_visible_volume_nl,
                roi=roi,
                tracked_nozzle_x_px=tracked_nozzle_x_px,
                config=config,
            )
        )

    material_details = [
        dict(detail)
        for detail in details
        if detail.get("component_volume_nl") is not None
        and (
            float(detail["component_volume_nl"]) >= float(config["detached_material_volume_min_nl"])
            or (
                detached_visible_volume_nl not in (None, 0.0)
                and float(detail["component_volume_nl"])
                >= (float(config["detached_material_volume_fraction_min"]) * float(detached_visible_volume_nl))
            )
        )
    ]
    symmetry_scores = [
        float(detail["axis_symmetry_score"])
        for detail in material_details
        if detail.get("axis_symmetry_score") is not None
    ]
    local_spans = [
        float(detail["local_centerline_span_px"])
        for detail in material_details
        if detail.get("local_centerline_span_px") is not None
    ]
    axis_offsets = [
        float(detail["axis_offset_px"])
        for detail in material_details
        if detail.get("axis_offset_px") is not None
    ]
    geometry_confidences = [
        float(detail["geometry_confidence"])
        for detail in material_details
        if detail.get("geometry_confidence") is not None
    ]
    geometry_reasons = []
    detached_ok = True
    for detail in material_details:
        if not bool(detail.get("geometry_ok")):
            detached_ok = False
            component_id = str(detail.get("component_id") or "detached_component")
            geometry_reasons.extend(
                [f"{component_id}:{reason}" for reason in list(detail.get("geometry_reasons") or [])]
            )

    return {
        "detached_volume_geometry_ok": bool(detached_ok),
        "detached_geometry_details": details,
        "min_detached_axis_symmetry_score": None if not symmetry_scores else float(min(symmetry_scores)),
        "max_detached_local_centerline_span_px": None if not local_spans else float(max(local_spans)),
        "max_detached_axis_offset_px": None if not axis_offsets else float(max(axis_offsets)),
        "detached_geometry_confidence": None if not geometry_confidences else float(min(geometry_confidences)),
        "detached_geometry_reasons": online_cal_mod._unique_strings(geometry_reasons),
    }


def _attached_optical_summary(
    *,
    frame_image,
    frame_color_order: str,
    attached_edge_rows: list[dict],
    attached_component: dict | None,
    roi: dict,
    visible_fluid_clearance_px,
    lower_row_fraction: float,
    config: dict,
    geometry_assessable: bool,
) -> dict:
    activation_clearance_px = float(config["optical_activation_clearance_px"])
    optical_confidence_active = bool(
        visible_fluid_clearance_px is not None
        and float(visible_fluid_clearance_px) <= activation_clearance_px
    )
    if not geometry_assessable or attached_component is None:
        return {
            "flow_optical_confidence_active": bool(optical_confidence_active),
            "optical_activation_clearance_px": activation_clearance_px,
            "lower_edge_jitter_px": None,
            "boundary_chroma_aberration_score": None,
            "flow_optical_confidence": None,
        }

    lower_rows = _lower_rows(attached_edge_rows, lower_fraction=float(lower_row_fraction))
    left_rms = _fit_residual_rms(lower_rows, x_key="x_left_px")
    right_rms = _fit_residual_rms(lower_rows, x_key="x_right_px")
    jitter_values = [
        float(value)
        for value in (left_rms, right_rms)
        if value is not None
    ]
    lower_edge_jitter_px = None if not jitter_values else float(max(jitter_values))

    boundary_chroma_aberration_score = None
    flow_optical_confidence = 1.0 if not optical_confidence_active else None
    try:
        display_frame = _coerce_bgr_frame(frame_image, color_order=frame_color_order)
        component_mask = _project_component_mask(attached_component, roi, display_frame.shape)
        if component_mask is not None and np.any(component_mask > 0) and lower_rows:
            boundary_mask = component_mask > 0
            eroded = cv2.erode(component_mask, np.ones((3, 3), dtype=np.uint8), iterations=1) > 0
            boundary_mask = boundary_mask & ~eroded
            y_threshold = int(lower_rows[0]["y_px"])
            boundary_mask[: max(0, y_threshold), :] = False
            if np.any(boundary_mask):
                b_channel = display_frame[:, :, 0].astype(np.float32)
                r_channel = display_frame[:, :, 2].astype(np.float32)
                chroma = np.abs(r_channel - b_channel)
                boundary_chroma_aberration_score = float(np.mean(chroma[boundary_mask]))
        if optical_confidence_active:
            image_height = int(display_frame.shape[0])
            lower_band_fraction = float(
                config.get("optical_lower_image_band_fraction")
                or config.get("optical_lower_row_fraction")
                or 0.25
            )
            lower_band_fraction = float(max(0.0, min(1.0, lower_band_fraction)))
            lower_band_height_px = int(max(1, np.ceil(float(image_height) * lower_band_fraction)))
            lower_band_y0 = int(max(0, image_height - lower_band_height_px))
            band_rows = [
                dict(row or {})
                for row in list(attached_edge_rows or [])
                if int(dict(row or {}).get("y_px") or 0) >= int(lower_band_y0)
            ]
            band_left_rms = _fit_residual_rms(band_rows, x_key="x_left_px")
            band_right_rms = _fit_residual_rms(band_rows, x_key="x_right_px")
            band_jitter_values = [
                float(value)
                for value in (band_left_rms, band_right_rms)
                if value is not None
            ]
            active_lower_edge_jitter_px = None if not band_jitter_values else float(max(band_jitter_values))
            active_boundary_chroma_aberration_score = None
            if component_mask is not None and np.any(component_mask > 0):
                band_boundary_mask = component_mask > 0
                band_eroded = cv2.erode(component_mask, np.ones((3, 3), dtype=np.uint8), iterations=1) > 0
                band_boundary_mask = band_boundary_mask & ~band_eroded
                band_boundary_mask[: max(0, lower_band_y0), :] = False
                if np.any(band_boundary_mask):
                    b_channel = display_frame[:, :, 0].astype(np.float32)
                    r_channel = display_frame[:, :, 2].astype(np.float32)
                    chroma = np.abs(r_channel - b_channel)
                    active_boundary_chroma_aberration_score = float(np.mean(chroma[band_boundary_mask]))
            flow_optical_confidence = _min_confidence(
                _confidence_smaller_better(
                    active_lower_edge_jitter_px,
                    full_at=float(config["optical_edge_jitter_confidence_full_px"]),
                    zero_at=float(config["optical_edge_jitter_confidence_zero_px"]),
                ),
                _confidence_smaller_better(
                    active_boundary_chroma_aberration_score,
                    full_at=float(config["optical_boundary_chroma_confidence_full"]),
                    zero_at=float(config["optical_boundary_chroma_confidence_zero"]),
                ),
            )
            if flow_optical_confidence is None:
                flow_optical_confidence = 1.0
    except Exception:
        boundary_chroma_aberration_score = None
        if not optical_confidence_active:
            flow_optical_confidence = 1.0
        else:
            flow_optical_confidence = 1.0
    return {
        "flow_optical_confidence_active": bool(optical_confidence_active),
        "optical_activation_clearance_px": activation_clearance_px,
        "lower_edge_jitter_px": lower_edge_jitter_px,
        "boundary_chroma_aberration_score": boundary_chroma_aberration_score,
        "flow_optical_confidence": flow_optical_confidence,
    }


def _summary_status(
    *,
    silhouette_qc_pass: bool,
    nozzle_qc_pass: bool,
    attached_width_px,
    visible_volume_nl,
    attached_bottom_clearance_px,
    attached_bottom_guard_px: int,
):
    if not silhouette_qc_pass:
        return "rejected_silhouette_qc"
    if not nozzle_qc_pass:
        return "rejected_nozzle_qc"
    if attached_width_px is None:
        return "rejected_width_qc"
    if visible_volume_nl is None:
        return "rejected_volume_qc"
    if attached_bottom_clearance_px is None:
        return "rejected_bottom_clearance_unavailable"
    if int(attached_bottom_clearance_px) <= int(attached_bottom_guard_px):
        return "rejected_bottom_guard"
    return "accepted"


def _coerce_display_frame(frame_image) -> np.ndarray:
    arr = np.asarray(frame_image)
    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3 and arr.shape[2] == 1:
        return cv2.cvtColor(arr[:, :, 0], cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        return arr[:, :, :3].copy()
    raise ValueError(f"Unsupported frame shape for online stream overlay: {getattr(arr, 'shape', None)}")


def _normalized_color_order(color_order: str | None, *, default: str = "bgr") -> str:
    text = str(color_order or default).strip().lower()
    if text in {"rgb", "bgr"}:
        return text
    raise ValueError(f"Unsupported color order: {color_order!r}")


def _coerce_analysis_gray_frame(frame_image, *, color_order: str = "bgr") -> np.ndarray:
    arr = np.asarray(frame_image)
    order = _normalized_color_order(color_order)
    if arr.ndim == 2:
        return arr.copy()
    if arr.ndim == 3 and arr.shape[2] == 1:
        return arr[:, :, 0].copy()
    if arr.ndim == 3 and arr.shape[2] == 3:
        conversion = cv2.COLOR_RGB2GRAY if order == "rgb" else cv2.COLOR_BGR2GRAY
        return cv2.cvtColor(arr, conversion)
    if arr.ndim == 3 and arr.shape[2] == 4:
        conversion = cv2.COLOR_RGBA2GRAY if order == "rgb" else cv2.COLOR_BGRA2GRAY
        return cv2.cvtColor(arr, conversion)
    raise ValueError(
        f"Unsupported frame shape for online stream grayscale conversion: {getattr(arr, 'shape', None)}"
    )


def _coerce_bgr_frame(frame_image, *, color_order: str = "bgr") -> np.ndarray:
    arr = np.asarray(frame_image)
    order = _normalized_color_order(color_order)
    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3 and arr.shape[2] == 1:
        return cv2.cvtColor(arr[:, :, 0], cv2.COLOR_GRAY2BGR)
    if arr.ndim == 3 and arr.shape[2] == 3:
        if order == "rgb":
            return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        return arr.copy()
    if arr.ndim == 3 and arr.shape[2] == 4:
        conversion = cv2.COLOR_RGBA2BGR if order == "rgb" else cv2.COLOR_BGRA2BGR
        return cv2.cvtColor(arr, conversion)
    raise ValueError(f"Unsupported frame shape for online stream color conversion: {getattr(arr, 'shape', None)}")


def _project_component_mask(component: dict, roi: dict, image_shape) -> np.ndarray | None:
    final_mask = component.get("final_mask")
    if final_mask is None:
        return None
    local_mask = np.asarray(final_mask)
    if local_mask.ndim != 2 or local_mask.size <= 0 or not np.any(local_mask > 0):
        return None

    image_h, image_w = image_shape[:2]
    x0 = max(0, min(int(roi.get("x0", 0)), image_w))
    y0 = max(0, min(int(roi.get("y0", 0)), image_h))
    x1 = max(x0, min(int(roi.get("x1", x0)), image_w))
    y1 = max(y0, min(int(roi.get("y1", y0)), image_h))
    target_h = max(0, y1 - y0)
    target_w = max(0, x1 - x0)
    if target_h <= 0 or target_w <= 0:
        return None

    copy_h = min(target_h, int(local_mask.shape[0]))
    copy_w = min(target_w, int(local_mask.shape[1]))
    if copy_h <= 0 or copy_w <= 0:
        return None

    full_mask = np.zeros((image_h, image_w), dtype=np.uint8)
    full_mask[y0 : y0 + copy_h, x0 : x0 + copy_w] = np.where(
        local_mask[:copy_h, :copy_w] > 0,
        255,
        0,
    ).astype(np.uint8)
    return full_mask


def _blend_component_overlay(image: np.ndarray, component_mask: np.ndarray, color, *, alpha: float) -> np.ndarray:
    if component_mask is None or not np.any(component_mask > 0):
        return image

    blended = image.copy()
    color_arr = np.asarray(color, dtype=np.float32)
    mask = component_mask > 0
    if np.any(mask):
        base = blended.astype(np.float32)
        base[mask] = ((1.0 - float(alpha)) * base[mask]) + (float(alpha) * color_arr)
        blended = np.clip(base, 0, 255).astype(np.uint8)

    contours, _hierarchy = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        cv2.drawContours(blended, contours, -1, tuple(int(v) for v in color), 2)
    return blended


def _compact_warning_text(warnings: list[str]) -> str | None:
    labels = [str(item or "").strip() for item in list(warnings or []) if str(item or "").strip()]
    if not labels:
        return None
    if len(labels) > 3:
        labels = [*labels[:3], "…"]
    return ", ".join(labels)


def _draw_online_stream_hud(image: np.ndarray, *, summary: dict, delay_us: int, emergence_time_us: int) -> np.ndarray:
    hud = image.copy()
    warning_text = _compact_warning_text(summary.get("warnings") or [])
    lines = [
        f"delay: {int(delay_us)} us ({int(delay_us - int(emergence_time_us)):+d} us from emergence)",
        f"status: {str(summary.get('status') or 'unknown')}",
        "visible volume: "
        + (
            "n/a"
            if summary.get("visible_volume_nl") is None
            else f"{float(summary['visible_volume_nl']):.3f} nL"
        ),
        "attached width: "
        + (
            "n/a"
            if summary.get("attached_width_px") is None
            else f"{float(summary['attached_width_px']):.2f} px"
        ),
    ]
    if warning_text:
        lines.append(f"warnings: {warning_text}")

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.48
    thickness = 1
    margin = 8
    line_gap = 7
    text_metrics = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in lines]
    box_width = min(
        int(hud.shape[1]) - (2 * margin),
        max((size[0] for size in text_metrics), default=0) + (2 * margin),
    )
    line_height = max((size[1] for size in text_metrics), default=12)
    box_height = (len(lines) * line_height) + (max(0, len(lines) - 1) * line_gap) + (2 * margin)

    overlay = hud.copy()
    cv2.rectangle(
        overlay,
        (margin, margin),
        (max(margin, margin + box_width), max(margin, margin + box_height)),
        (20, 20, 20),
        -1,
    )
    hud = cv2.addWeighted(overlay, 0.75, hud, 0.25, 0.0)

    status_color = (0, 200, 0) if str(summary.get("status") or "") == "accepted" else (0, 165, 255)
    y = margin + line_height
    for index, line in enumerate(lines):
        color = status_color if index == 1 else (235, 235, 235)
        cv2.putText(
            hud,
            line,
            (margin + 6, y),
            font,
            font_scale,
            color,
            thickness,
            lineType=cv2.LINE_AA,
        )
        y += line_height + line_gap
    return hud


def _build_online_stream_overlay(
    frame_image,
    *,
    stage3_frame: dict,
    summary: dict,
    delay_us: int,
    emergence_time_us: int,
    alpha: float = 0.40,
) -> np.ndarray:
    overlay = _coerce_display_frame(frame_image)
    roi = dict(stage3_frame.get("roi") or {})
    for component in list(stage3_frame.get("accepted_components") or []):
        component_mask = _project_component_mask(component, roi, overlay.shape)
        color = silhouette_mod._component_color(component.get("component_role", "detached_accepted"))
        overlay = _blend_component_overlay(overlay, component_mask, color, alpha=float(alpha))

    tracked_row = dict(stage3_frame.get("tracked_row") or {})
    metric_row = dict(stage3_frame.get("metric_row") or {})
    overlay = silhouette_mod._draw_nozzle_context(
        overlay,
        nozzle_x_px=tracked_row.get("tracked_nozzle_x_px"),
        nozzle_y_px=tracked_row.get("tracked_nozzle_y_px"),
        cutoff_y_px=metric_row.get("cutoff_y_px"),
        x0_px=0,
        x1_px=max(0, overlay.shape[1] - 1),
    )
    return _draw_online_stream_hud(
        overlay,
        summary=summary,
        delay_us=int(delay_us),
        emergence_time_us=int(emergence_time_us),
    )


def analyze_online_stream_frame(
    *,
    frame_image,
    background_image,
    nozzle_center_px,
    delay_us: int,
    emergence_time_us: int,
    analysis_config: dict | None = None,
    capture_ref: dict | None = None,
    capture_index: int | None = None,
    frame_color_order: str = "bgr",
    background_color_order: str | None = None,
    sticky_window_state: dict | None = None,
    pixel_size_um: float | None = None,
    _adaptive_retry: bool = True,
) -> dict:
    config = _resolved_analysis_config(analysis_config)
    frame_color_order = _normalized_color_order(frame_color_order)
    background_color_order = _normalized_color_order(
        background_color_order,
        default=frame_color_order,
    )
    stage3_frame = silhouette_mod._analyze_stage3_gray(
        "online_stream_runtime",
        _frame_row(
            delay_us=int(delay_us),
            emergence_time_us=int(emergence_time_us),
            capture_ref=capture_ref,
            capture_index=capture_index,
        ),
        _tracked_row(nozzle_center_px),
        _coerce_analysis_gray_frame(frame_image, color_order=frame_color_order),
        roi_width_frac=_ROI_WIDTH_FRAC,
        roi_top_frac=_ROI_TOP_FRAC,
        roi_bottom_frac=_ROI_BOTTOM_FRAC,
        corridor_width_frac=_CORRIDOR_WIDTH_FRAC,
        nozzle_guard_px=int(config["nozzle_guard_px"]),
        min_component_area_px=int(config["min_component_area_px"]),
        adaptive_roi_expansion_enabled=bool(config["adaptive_roi_expansion_enabled"])
        and not bool(_adaptive_retry),
        adaptive_roi_edge_margin_px=int(config["adaptive_roi_edge_margin_px"]),
        adaptive_roi_expansion_step_px=int(config["adaptive_roi_expansion_step_px"]),
        adaptive_roi_max_expansion_px=int(config["adaptive_roi_max_expansion_px"]),
    )
    stage4_frame = volume_mod._analyze_stage4_frame(
        stage3_frame,
        near_bottom_px=int(config["detached_near_bottom_warning_px"]),
        pixel_size_um=pixel_size_um,
    )

    stage3_metric_row = dict(stage3_frame.get("metric_row") or {})
    frame_metric_row = dict(stage4_frame.get("frame_metric_row") or {})
    component_rows = [dict(row) for row in list(stage3_frame.get("component_rows") or [])]
    component_volume_rows = [dict(row) for row in list(stage4_frame.get("component_volume_rows") or [])]
    accepted_components = [dict(component) for component in list(stage3_frame.get("accepted_components") or [])]
    roi = dict(stage3_frame.get("roi") or {})
    attached_component_row = next(
        (row for row in component_rows if str(row.get("component_role") or "") == "attached_primary"),
        None,
    )
    attached_component = next(
        (
            dict(component)
            for component in accepted_components
            if str(component.get("component_role") or "") == "attached_primary"
        ),
        None,
    )
    attached_edge_rows = [] if attached_component is None else list(attached_component.get("edge_rows") or [])
    width_metrics = _band_width_metrics(
        stage3_metric_row,
        attached_edge_rows,
        near_nozzle_band_top_px=int(config["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(config["near_nozzle_band_height_px"]),
        min_band_valid_rows=int(config["min_band_valid_rows"]),
        delay_from_emergence_us=int(delay_us) - int(emergence_time_us),
        sticky_window_state=sticky_window_state,
        sticky_window_enabled=bool(config["tail_width_sticky_window_enabled"]),
        window_bank_enabled=bool(config["tail_width_window_bank_enabled"]),
        window_delay_lock_enabled=bool(config["tail_width_window_delay_lock_enabled"]),
        window_monotonic_by_delay_enabled=bool(
            config["tail_width_window_monotonic_by_delay_enabled"]
        ),
        sticky_window_confirm_frames=int(config["tail_width_sticky_window_confirm_frames"]),
        sticky_window_min_switch_drop_px=float(config["tail_width_sticky_window_min_switch_drop_px"]),
        sticky_window_min_switch_drop_frac=float(config["tail_width_sticky_window_min_switch_drop_frac"]),
        sticky_window_max_step_multiplier=int(config["tail_width_sticky_window_max_step_multiplier"]),
    )

    silhouette_qc_pass = str(stage3_metric_row.get("silhouette_status") or "") == "ok"
    cutoff_y_px = stage3_metric_row.get("cutoff_y_px")
    selected_component_top_y_px = stage3_metric_row.get("selected_component_top_y_px")
    nozzle_qc_pass = bool(
        silhouette_qc_pass
        and cutoff_y_px is not None
        and selected_component_top_y_px is not None
        and int(selected_component_top_y_px) <= int(cutoff_y_px) + int(config["near_nozzle_band_top_px"])
    )
    attached_width_px = width_metrics.get("attached_width_px")
    breakup_metrics = _attached_near_nozzle_breakup(
        stage3_metric_row,
        attached_component_row,
        width_metrics,
        config=config,
    )
    continuation_metrics = _residue_stub_with_detached_continuation(
        attached_component_row,
        component_rows,
        accepted_components,
        breakup_metrics,
        config=config,
    )
    residue_stub_with_detached_continuation = bool(
        continuation_metrics.get("residue_stub_with_detached_continuation")
    )
    attached_near_nozzle_breakup_detected = bool(
        breakup_metrics.get("attached_near_nozzle_breakup_detected")
        or residue_stub_with_detached_continuation
    )
    attached_band_extension_px = breakup_metrics.get("attached_band_extension_px")
    attached_breakup_min_extension_px = breakup_metrics.get(
        "attached_breakup_min_extension_px"
    )
    if attached_near_nozzle_breakup_detected:
        attached_width_px = None
    visible_volume_nl = frame_metric_row.get("total_visible_volume_nl")
    attached_bottom_clearance_px = _attached_component_clearance(stage3_metric_row, attached_component_row)
    detached_warning = _detached_near_bottom_warning(
        stage3_metric_row,
        component_rows,
        threshold_px=int(config["detached_near_bottom_warning_px"]),
    )
    near_nozzle_detached_warning = _near_nozzle_detached_warning(
        stage3_metric_row,
        component_rows,
        near_nozzle_band_top_px=int(config["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(config["near_nozzle_band_height_px"]),
    )
    direct_departure = bool(
        silhouette_qc_pass
        and cutoff_y_px is not None
        and selected_component_top_y_px is not None
        and int(selected_component_top_y_px) > int(cutoff_y_px) + int(config["near_nozzle_band_top_px"])
    )
    separated_from_nozzle_landmark = bool(
        silhouette_qc_pass
        and (direct_departure or residue_stub_with_detached_continuation)
    )
    separation_mode = "none"
    if direct_departure:
        separation_mode = "selected_component_departed"
    elif residue_stub_with_detached_continuation:
        separation_mode = "detached_continuation_below_stub"
    effective_stream_owner = (
        "detached_continuation"
        if residue_stub_with_detached_continuation
        else "attached_primary"
    )
    tail_width_usable = bool(
        silhouette_qc_pass
        and nozzle_qc_pass
        and attached_width_px is not None
    )
    tail_landmark_usable = bool(
        silhouette_qc_pass and separated_from_nozzle_landmark
    )
    landmark_reason = "separated_from_nozzle" if tail_landmark_usable else None
    attached_bottom_guard_hit = bool(
        attached_bottom_clearance_px is not None
        and int(attached_bottom_clearance_px) <= int(config["attached_bottom_guard_px"])
    )
    late_frame_warning = bool(attached_bottom_guard_hit or detached_warning)
    status = _summary_status(
        silhouette_qc_pass=bool(silhouette_qc_pass),
        nozzle_qc_pass=bool(nozzle_qc_pass),
        attached_width_px=attached_width_px,
        visible_volume_nl=visible_volume_nl,
        attached_bottom_clearance_px=attached_bottom_clearance_px,
        attached_bottom_guard_px=int(config["attached_bottom_guard_px"]),
    )
    measurement_qc_pass = str(status) == "accepted"
    geometry_assessable = bool(measurement_qc_pass)
    attached_geometry = _attached_geometry_summary(
        attached_edge_rows,
        lower_row_fraction=float(config["attached_lower_centerline_row_fraction"]),
        min_rows=int(config["attached_lower_centerline_min_rows"]),
        span_max_px=float(config["attached_lower_centerline_span_max_px"]),
        config=config,
        geometry_assessable=geometry_assessable,
    )
    detached_geometry = _detached_geometry_summary(
        accepted_components=accepted_components,
        component_volume_rows=component_volume_rows,
        detached_visible_volume_nl=frame_metric_row.get("detached_visible_volume_nl"),
        roi=roi,
        tracked_nozzle_x_px=stage3_metric_row.get("tracked_nozzle_x_px"),
        config=config,
        geometry_assessable=geometry_assessable,
    )
    attached_geometry_ok = attached_geometry.get("attached_volume_geometry_ok")
    detached_geometry_ok = detached_geometry.get("detached_volume_geometry_ok")
    visible_fluid_clearance_px = _visible_fluid_clearance_px(
        frame_metric_row=frame_metric_row,
        attached_bottom_clearance_px=attached_bottom_clearance_px,
    )
    flow_geometry_confidence = None
    if geometry_assessable:
        flow_geometry_confidence = _min_confidence(
            attached_geometry.get("attached_geometry_confidence"),
            detached_geometry.get("detached_geometry_confidence"),
        )
        if flow_geometry_confidence is None:
            flow_geometry_confidence = 1.0
    optical_summary = _attached_optical_summary(
        frame_image=frame_image,
        frame_color_order=frame_color_order,
        attached_edge_rows=attached_edge_rows,
        attached_component=attached_component,
        roi=roi,
        visible_fluid_clearance_px=visible_fluid_clearance_px,
        lower_row_fraction=float(config["optical_lower_row_fraction"]),
        config=config,
        geometry_assessable=geometry_assessable,
    )
    flow_optical_confidence = optical_summary.get("flow_optical_confidence")
    flow_point_confidence = _min_confidence(
        flow_geometry_confidence,
        flow_optical_confidence,
    )
    if geometry_assessable and flow_point_confidence is None:
        flow_point_confidence = 1.0
    flow_volume_geometry_ok = None
    flow_volume_geometry_reasons = []
    flow_volume_geometry_warnings = []
    if geometry_assessable:
        flow_volume_geometry_warnings = online_cal_mod._unique_strings(
            list(attached_geometry.get("attached_geometry_warnings") or [])
        )
        flow_volume_geometry_reasons = online_cal_mod._unique_strings(
            list(attached_geometry.get("attached_geometry_reasons") or [])
            + list(detached_geometry.get("detached_geometry_reasons") or [])
        )
        flow_volume_geometry_ok = bool(
            attached_geometry_ok is not False and detached_geometry_ok is not False
        )
    plausible_unaccepted_component_count = stage3_metric_row.get(
        "plausible_unaccepted_component_count"
    )
    plausible_unaccepted_visible_volume_nl = frame_metric_row.get(
        "plausible_unaccepted_visible_volume_nl"
    )
    flow_volume_complete_ok = None
    flow_volume_completeness_reasons = []
    if geometry_assessable:
        flow_volume_complete_ok = True
        if (
            plausible_unaccepted_visible_volume_nl is not None
            and float(plausible_unaccepted_visible_volume_nl)
            >= float(config["flow_volume_incomplete_material_volume_nl"])
        ):
            flow_volume_complete_ok = False
            flow_volume_completeness_reasons.append(
                "material_plausible_unaccepted_detached"
            )
    flow_measurement_usable = bool(
        measurement_qc_pass
        and flow_volume_geometry_ok is not False
        and flow_volume_complete_ok is not False
    )

    warnings = []
    if not silhouette_qc_pass:
        warnings.append("silhouette_qc_failed")
    if silhouette_qc_pass and not nozzle_qc_pass:
        warnings.append("nozzle_qc_failed")
    if attached_near_nozzle_breakup_detected:
        warnings.append("attached_near_nozzle_breakup")
    if residue_stub_with_detached_continuation:
        warnings.append("residue_stub_with_detached_continuation")
    if silhouette_qc_pass and attached_width_px is None and not separated_from_nozzle_landmark:
        warnings.append("attached_width_unavailable")
    if silhouette_qc_pass and visible_volume_nl is None:
        warnings.append("visible_volume_unavailable")
    if attached_bottom_clearance_px is None:
        warnings.append("attached_bottom_clearance_unavailable")
    elif attached_bottom_guard_hit:
        warnings.append("attached_bottom_guard_hit")
    if detached_warning:
        warnings.append("detached_near_bottom_warning")
    if near_nozzle_detached_warning:
        warnings.append("near_nozzle_detached_warning")
    if measurement_qc_pass and flow_volume_geometry_ok is False:
        warnings.append("flow_volume_geometry_not_ok")
    for geometry_warning in list(flow_volume_geometry_warnings or []):
        if measurement_qc_pass:
            warnings.append(str(geometry_warning))
    if measurement_qc_pass and flow_volume_complete_ok is False:
        warnings.append("flow_volume_incomplete")

    if background_image is not None:
        try:
            bg_gray = _coerce_analysis_gray_frame(
                background_image,
                color_order=background_color_order,
            )
            if bg_gray.shape[:2] != stage3_frame["gray"].shape[:2]:
                warnings.append("background_shape_mismatch")
        except Exception:
            warnings.append("background_image_unavailable")

    failure_reason = stage3_metric_row.get("failure_reason")
    if residue_stub_with_detached_continuation:
        failure_reason = (
            "detached continuation separated from a short nozzle residue stub"
        )
    elif direct_departure:
        failure_reason = "selected component separated from nozzle band"
    elif attached_near_nozzle_breakup_detected:
        failure_reason = (
            "attached stream terminates too close to the nozzle while detached droplets are already present"
        )
    elif status == "rejected_nozzle_qc":
        failure_reason = "selected component too far below nozzle cutoff"
    elif status == "rejected_width_qc":
        failure_reason = "attached near-nozzle width unavailable"
    elif status == "rejected_volume_qc":
        failure_reason = "visible volume unavailable"
    elif status == "rejected_bottom_clearance_unavailable":
        failure_reason = "attached bottom clearance unavailable"
    elif status == "rejected_bottom_guard":
        failure_reason = "attached primary reached bottom guard"

    summary = {
        "status": str(status),
        "delay_from_emergence_us": int(delay_us - int(emergence_time_us)),
        "measurement_qc_pass": bool(measurement_qc_pass),
        "nozzle_qc_pass": bool(nozzle_qc_pass),
        "silhouette_qc_pass": bool(silhouette_qc_pass),
        "silhouette_status": stage3_metric_row.get("silhouette_status"),
        "failure_reason": failure_reason,
        "attached_width_px": attached_width_px,
        "attached_width_mode": width_metrics.get("attached_width_mode"),
        "pixel_size_um": stage4_frame.get("pixel_size_um"),
        "visible_volume_nl": visible_volume_nl,
        "attached_bottom_clearance_px": attached_bottom_clearance_px,
        "min_accepted_fluid_distance_from_bottom_px": frame_metric_row.get(
            "min_accepted_fluid_distance_from_bottom_px"
        ),
        "accepted_component_count": stage3_metric_row.get("accepted_component_count"),
        "accepted_detached_component_count": stage3_metric_row.get(
            "accepted_detached_component_count"
        ),
        "plausible_unaccepted_component_count": plausible_unaccepted_component_count,
        "plausible_unaccepted_visible_volume_nl": plausible_unaccepted_visible_volume_nl,
        "attached_lower_centerline_span_px": attached_geometry.get(
            "attached_lower_centerline_span_px"
        ),
        "attached_lower_centerline_rms_px": attached_geometry.get(
            "attached_lower_centerline_rms_px"
        ),
        "attached_volume_geometry_ok": attached_geometry_ok,
        "detached_volume_geometry_ok": detached_geometry_ok,
        "detached_geometry_details": detached_geometry.get("detached_geometry_details"),
        "min_detached_axis_symmetry_score": detached_geometry.get(
            "min_detached_axis_symmetry_score"
        ),
        "max_detached_local_centerline_span_px": detached_geometry.get(
            "max_detached_local_centerline_span_px"
        ),
        "max_detached_axis_offset_px": detached_geometry.get("max_detached_axis_offset_px"),
        "flow_geometry_confidence": flow_geometry_confidence,
        "flow_optical_confidence": flow_optical_confidence,
        "flow_point_confidence": flow_point_confidence,
        "flow_optical_confidence_active": optical_summary.get("flow_optical_confidence_active"),
        "optical_activation_clearance_px": optical_summary.get("optical_activation_clearance_px"),
        "lower_edge_jitter_px": optical_summary.get("lower_edge_jitter_px"),
        "boundary_chroma_aberration_score": optical_summary.get(
            "boundary_chroma_aberration_score"
        ),
        "flow_volume_geometry_ok": flow_volume_geometry_ok,
        "flow_volume_geometry_reasons": flow_volume_geometry_reasons,
        "flow_volume_geometry_warnings": flow_volume_geometry_warnings,
        "flow_volume_complete_ok": flow_volume_complete_ok,
        "flow_volume_completeness_reasons": flow_volume_completeness_reasons,
        "flow_measurement_usable": bool(flow_measurement_usable),
        "tail_width_usable": bool(tail_width_usable),
        "separated_from_nozzle_landmark": bool(separated_from_nozzle_landmark),
        "tail_landmark_usable": bool(tail_landmark_usable),
        "landmark_reason": landmark_reason,
        "effective_stream_owner": effective_stream_owner,
        "separation_mode": separation_mode,
        "residue_stub_with_detached_continuation": bool(
            residue_stub_with_detached_continuation
        ),
        "detached_continuation_component_id": continuation_metrics.get(
            "detached_continuation_component_id"
        ),
        "detached_continuation_gap_px": continuation_metrics.get(
            "detached_continuation_gap_px"
        ),
        "detached_continuation_height_px": continuation_metrics.get(
            "detached_continuation_height_px"
        ),
        "detached_continuation_row_count": continuation_metrics.get(
            "detached_continuation_row_count"
        ),
        "detached_near_bottom_warning": bool(detached_warning),
        "near_nozzle_detached_warning": bool(near_nozzle_detached_warning),
        "attached_near_nozzle_breakup_detected": bool(attached_near_nozzle_breakup_detected),
        "attached_band_extension_px": attached_band_extension_px,
        "attached_breakup_min_extension_px": attached_breakup_min_extension_px,
        "late_frame_warning": bool(late_frame_warning),
        "warnings": online_cal_mod._copy_warnings(warnings),
        "selected_component_top_y_px": selected_component_top_y_px,
        "cutoff_y_px": cutoff_y_px,
        "adaptive_roi_expansion_triggered": bool(
            stage3_metric_row.get("adaptive_roi_expansion_triggered")
        ),
        "adaptive_roi_expansion_sides": list(
            stage3_metric_row.get("adaptive_roi_expansion_sides") or []
        ),
        "adaptive_roi_expansion_iterations": stage3_metric_row.get(
            "adaptive_roi_expansion_iterations"
        ),
        "adaptive_roi_left_expansion_px": stage3_metric_row.get(
            "adaptive_roi_left_expansion_px"
        ),
        "adaptive_roi_right_expansion_px": stage3_metric_row.get(
            "adaptive_roi_right_expansion_px"
        ),
        "adaptive_roi_stop_reason": stage3_metric_row.get("adaptive_roi_stop_reason"),
        "base_roi_x0": stage3_metric_row.get("base_roi_x0"),
        "base_roi_x1": stage3_metric_row.get("base_roi_x1"),
        "base_corridor_x0": stage3_metric_row.get("base_corridor_x0"),
        "base_corridor_x1": stage3_metric_row.get("base_corridor_x1"),
        "selected_component_corridor_left_clearance_px": stage3_metric_row.get(
            "selected_component_corridor_left_clearance_px"
        ),
        "selected_component_corridor_right_clearance_px": stage3_metric_row.get(
            "selected_component_corridor_right_clearance_px"
        ),
        "width_valid_row_count": width_metrics.get("width_valid_row_count"),
        "root_band_width_px": width_metrics.get("root_band_width_px"),
        "root_band_width_iqr_px": width_metrics.get("root_band_width_iqr_px"),
        "root_band_half_delta_px": width_metrics.get("root_band_half_delta_px"),
        "selected_band_y0_px": width_metrics.get("selected_band_y0_px"),
        "selected_band_y1_px": width_metrics.get("selected_band_y1_px"),
        "selected_band_step_index": width_metrics.get("selected_band_step_index"),
        "root_band_step_index": width_metrics.get("root_band_step_index"),
        "selected_band_valid_row_count": width_metrics.get("selected_band_valid_row_count"),
        "spread_fallback_triggered": bool(width_metrics.get("spread_fallback_triggered")),
        "candidate_window_count": width_metrics.get("candidate_window_count"),
        "tail_width_window_candidates": width_metrics.get("tail_width_window_candidates") or [],
        "sticky_window_active": bool(width_metrics.get("sticky_window_active")),
        "sticky_window_previous_y0_px": width_metrics.get("sticky_window_previous_y0_px"),
        "sticky_window_previous_y1_px": width_metrics.get("sticky_window_previous_y1_px"),
        "sticky_window_instant_y0_px": width_metrics.get("sticky_window_instant_y0_px"),
        "sticky_window_instant_y1_px": width_metrics.get("sticky_window_instant_y1_px"),
        "sticky_window_selected_reason": width_metrics.get("sticky_window_selected_reason"),
        "sticky_window_candidate_streak": width_metrics.get("sticky_window_candidate_streak"),
        "sticky_window_switch_blocked": bool(width_metrics.get("sticky_window_switch_blocked")),
        "window_delay_lock_active": bool(width_metrics.get("window_delay_lock_active")),
        "window_locked_reused": bool(width_metrics.get("window_locked_reused")),
        "window_locked_invalid": bool(width_metrics.get("window_locked_invalid")),
        "window_monotonic_lower_bound_step_index": width_metrics.get(
            "window_monotonic_lower_bound_step_index"
        ),
        "window_monotonic_upper_bound_step_index": width_metrics.get(
            "window_monotonic_upper_bound_step_index"
        ),
        "window_monotonic_upward_move_blocked": bool(
            width_metrics.get("window_monotonic_upward_move_blocked")
        ),
        "next_sticky_window_state": width_metrics.get("next_sticky_window_state"),
        "attached_bottom_guard_hit": bool(attached_bottom_guard_hit),
    }
    late_coverage_candidate, late_coverage_metric = online_cal_mod.is_online_stream_flow_late_coverage_candidate(
        {**summary, "delay_accepted": bool(flow_measurement_usable)}
    )
    summary["late_coverage_candidate"] = bool(late_coverage_candidate)
    summary["late_coverage_metric"] = late_coverage_metric

    if bool(_adaptive_retry) and _adaptive_roi_retry_needed(summary, config):
        retry_config = dict(config)
        retry_config["adaptive_roi_expansion_enabled"] = True
        return analyze_online_stream_frame(
            frame_image=frame_image,
            background_image=background_image,
            nozzle_center_px=nozzle_center_px,
            delay_us=int(delay_us),
            emergence_time_us=int(emergence_time_us),
            analysis_config=retry_config,
            capture_ref=capture_ref,
            capture_index=capture_index,
            frame_color_order=frame_color_order,
            background_color_order=background_color_order,
            sticky_window_state=sticky_window_state,
            pixel_size_um=pixel_size_um,
            _adaptive_retry=False,
        )
    if bool(_adaptive_retry) and bool(config.get("adaptive_roi_expansion_enabled")):
        summary["adaptive_roi_stop_reason"] = "retry_not_needed"

    overlay = None
    try:
        overlay = _build_online_stream_overlay(
            frame_image,
            stage3_frame=stage3_frame,
            summary=summary,
            delay_us=int(delay_us),
            emergence_time_us=int(emergence_time_us),
            alpha=0.40,
        )
    except Exception:
        overlay = None

    return {
        "summary": summary,
        "overlay": overlay,
    }
