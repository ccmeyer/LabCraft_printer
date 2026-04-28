from __future__ import annotations

import math

import numpy as np

from tools.stream_analysis import online_calibration as online_cal_mod

try:
    from tools.stream_analysis import segmented_tail as segmented_tail_mod
except Exception:  # pragma: no cover - diagnostic path degrades safely.
    segmented_tail_mod = None


SEARCH_METHOD = "separation_landmark_backtrack_v1"
TAIL_SETTLING_SELECTION_METHOD = "settling_progress90_after_long_shoulder"
TAIL_SETTLING_PROGRESS_THRESHOLD = 0.90
TAIL_SETTLING_INTERP_STEP_US = 25
TAIL_SETTLING_MIN_SAVGOL_WINDOW = 5
TAIL_SETTLING_MAX_SAVGOL_WINDOW = 7
TAIL_SETTLING_MIN_COLLAPSE_WINDOW_US = 150
TAIL_SETTLING_MIN_DELAY_SHIFT_US = 50

DEFAULT_ONLINE_TAIL_POLICY = {
    "scout_landmark_width_frac": 0.95,
    "plateau_width_frac": 0.995,
    "departure_width_frac": 0.99,
    "backup_landmark_confirm_count": 2,
    "backup_landmark_immediate_width_frac": 0.85,
    "resolver_plateau_width_drop_px": 1.0,
    "resolver_transition_width_drop_px": 2.0,
    "resolver_transition_width_drop_frac": 0.03,
    "resolver_collapse_width_drop_px": 4.0,
    "resolver_collapse_width_frac": 0.95,
    "resolver_collapse_width_drop_frac": 0.05,
    "resolver_confirmation_window_us": 100,
    "consecutive_failed_tail_delays_stop": 2,
    "scout_step_us": 500,
    "scout_replicates": 1,
    "max_scout_delay_count": 10,
    "backtrack_step_us": 50,
    "backtrack_replicates": 1,
    "fine_prepad_us": 100,
    "fine_postpad_us": 100,
    "reserved_backtrack_capture_count": 15,
    "tail_right_extension_enabled": True,
    "tail_right_extension_max_us": 300,
    "tail_right_extension_min_falling_drop_px": 2.0,
}


def _to_int(value, default: int | None = None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default


def _to_float_or_none(value):
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return parsed
    except Exception:
        return None


def _copy_warnings(value) -> list[str]:
    warnings = []
    for item in list(value or []):
        label = str(item or "").strip()
        if label:
            warnings.append(label)
    return warnings


def _copy_jsonish(value):
    if isinstance(value, dict):
        return {str(key): _copy_jsonish(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_jsonish(item) for item in value]
    return value


def _unique_strings(values) -> list[str]:
    output = []
    seen = set()
    for value in list(values or []):
        label = str(value or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        output.append(label)
    return output


def _median_or_none(values):
    clean = []
    for value in list(values or []):
        parsed = _to_float_or_none(value)
        if parsed is not None:
            clean.append(float(parsed))
    if not clean:
        return None
    clean.sort()
    middle = len(clean) // 2
    if len(clean) % 2 == 1:
        return float(clean[middle])
    return float((clean[middle - 1] + clean[middle]) / 2.0)


def _resolved_policy(policy: dict | None = None) -> dict:
    merged = dict(DEFAULT_ONLINE_TAIL_POLICY)
    alias_map = {
        "coarse_trigger_width_frac": "scout_landmark_width_frac",
        "coarse_step_us": "scout_step_us",
        "coarse_replicates": "scout_replicates",
        "refine_step_us": "backtrack_step_us",
        "refine_replicates": "backtrack_replicates",
        "reserved_refine_capture_count": "reserved_backtrack_capture_count",
    }
    provided = dict(policy or {})
    for old_key, new_key in alias_map.items():
        if old_key in provided and new_key not in provided:
            provided[new_key] = provided.get(old_key)
    for key, default_value in DEFAULT_ONLINE_TAIL_POLICY.items():
        if key not in provided:
            continue
        if isinstance(default_value, bool):
            merged[key] = bool(provided.get(key))
        elif isinstance(default_value, int):
            merged[key] = max(0, _to_int(provided.get(key), default_value))
        else:
            merged[key] = float(provided.get(key))
    return merged


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
                merged[key] = _to_int(config.get(key), default_value)
    return merged


def _remaining_hard_budget(capture_budget: dict | None) -> int:
    budget = dict(capture_budget or {})
    remaining_hard = _to_int(budget.get("captures_remaining_hard"))
    if remaining_hard is not None:
        return max(0, int(remaining_hard))
    hard_limit = _to_int(budget.get("hard_limit"), 0)
    captures_used = _to_int(budget.get("captures_used"), 0)
    return max(0, int(hard_limit - captures_used))


def _sorted_unique_delays(values) -> list[int]:
    delays = []
    seen = set()
    for value in list(values or []):
        parsed = _to_int(value)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        delays.append(int(parsed))
    delays.sort()
    return delays


def _baseline_width_px_for_summary(summary: dict, median_width_px=None) -> float | None:
    if median_width_px is None:
        median_width_px = _to_float_or_none(summary.get("median_width_px"))
    width_ratio_to_baseline = _to_float_or_none(summary.get("width_ratio_to_baseline"))
    if (
        median_width_px is not None
        and width_ratio_to_baseline is not None
        and float(width_ratio_to_baseline) > 0.0
    ):
        return float(float(median_width_px) / float(width_ratio_to_baseline))
    width_drop_from_baseline_px = _to_float_or_none(summary.get("width_drop_from_baseline_px"))
    if median_width_px is not None and width_drop_from_baseline_px is not None:
        return float(float(median_width_px) + float(width_drop_from_baseline_px))
    return None


def _material_width_drop_threshold_px(
    summary: dict,
    resolved_policy: dict,
    *,
    px_key: str,
    frac_key: str | None = None,
) -> float:
    threshold_px = float(resolved_policy.get(px_key, 0.0) or 0.0)
    if frac_key is not None:
        baseline_width_px = _baseline_width_px_for_summary(summary)
        frac = _to_float_or_none(resolved_policy.get(frac_key))
        if baseline_width_px is not None and frac is not None:
            threshold_px = max(float(threshold_px), float(baseline_width_px) * float(frac))
    return float(threshold_px)


def _is_backup_width_collapse_landmark(summary: dict | None) -> bool:
    row = dict(summary or {})
    return bool(row.get("backup_width_collapse_landmark")) or str(
        row.get("landmark_reason") or ""
    ) == "strong_width_collapse_backup"


def _backup_landmark_confirmation(
    *,
    delay_summary: dict,
    scout_summaries: list[dict] | None,
    attempted_delay_count: int,
    planned_delay_count: int,
    resolved_policy: dict,
) -> dict:
    width_ratio = _to_float_or_none(delay_summary.get("width_ratio_to_baseline"))
    immediate_width_frac = float(resolved_policy["backup_landmark_immediate_width_frac"])
    if width_ratio is not None and float(width_ratio) <= immediate_width_frac:
        return {
            "confirmed": True,
            "reason": "severe_backup_width_collapse",
            "warnings": [],
        }

    history = [dict(row or {}) for row in list(scout_summaries or [])]
    current_delay_us = _to_int(delay_summary.get("delay_us"))
    if not history or _to_int(history[-1].get("delay_us")) != current_delay_us:
        history.append(dict(delay_summary))
    consecutive = 0
    for row in reversed(history):
        if _is_backup_width_collapse_landmark(row):
            consecutive += 1
        else:
            break
    confirm_count = max(1, _to_int(resolved_policy.get("backup_landmark_confirm_count"), 2))
    if consecutive >= int(confirm_count):
        return {
            "confirmed": True,
            "reason": "confirmed_backup_width_collapse",
            "warnings": [],
        }

    if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
        return {
            "confirmed": True,
            "reason": "final_scout_backup_width_collapse",
            "warnings": ["tail_backup_landmark_final_scout"],
        }

    return {
        "confirmed": False,
        "reason": "unconfirmed_backup_width_collapse",
        "warnings": ["tail_backup_landmark_unconfirmed"],
    }


def compress_online_stream_tail_backtrack_plan(
    *,
    delay_sequence: list[int] | None,
    left_endpoint_delay_us: int | None,
    landmark_delay_us: int | None,
    backtrack_step_us: int,
    backtrack_replicates: int = 1,
    fine_postpad_us: int | None = None,
    available_capture_count: int | None = None,
    dense_window_us: int = 400,
    preserved_postpad_us: int = 100,
    plateau_coarse_step_us: int = 100,
    force_compression: bool = False,
) -> dict:
    sequence = _sorted_unique_delays(delay_sequence)
    left_delay_us = _to_int(left_endpoint_delay_us)
    landmark_delay_value = _to_int(landmark_delay_us)
    step_us = max(1, _to_int(backtrack_step_us, DEFAULT_ONLINE_TAIL_POLICY["backtrack_step_us"]))
    replicate_count = max(1, _to_int(backtrack_replicates, 1))
    requested_capture_count = int(len(sequence) * replicate_count)
    if not sequence or left_delay_us is None or landmark_delay_value is None:
        return {
            "delay_sequence": sequence,
            "requested_capture_count": int(requested_capture_count),
            "applied_capture_count": int(requested_capture_count),
            "compressed": False,
        }

    available_delay_slots = None
    if available_capture_count is not None:
        available_delay_slots = max(0, int(_to_int(available_capture_count, 0)) // int(replicate_count))
        if int(len(sequence)) <= int(available_delay_slots) and not bool(force_compression):
            return {
                "delay_sequence": sequence,
                "requested_capture_count": int(requested_capture_count),
                "applied_capture_count": int(requested_capture_count),
                "compressed": False,
            }
    elif not bool(force_compression):
        return {
            "delay_sequence": sequence,
            "requested_capture_count": int(requested_capture_count),
            "applied_capture_count": int(requested_capture_count),
            "compressed": False,
        }

    keep_postpad_us = max(0, min(int(preserved_postpad_us), max(0, _to_int(fine_postpad_us, preserved_postpad_us))))
    keep_end_delay_us = int(landmark_delay_value + keep_postpad_us)
    trimmed_sequence = [
        int(delay_us)
        for delay_us in sequence
        if int(delay_us) >= int(left_delay_us) and int(delay_us) <= int(keep_end_delay_us)
    ]
    dense_start_delay_us = int(landmark_delay_value - max(0, int(dense_window_us)))
    dense_zone = [int(delay_us) for delay_us in trimmed_sequence if int(delay_us) >= int(dense_start_delay_us)]
    coarse_zone = [int(delay_us) for delay_us in trimmed_sequence if int(delay_us) < int(dense_start_delay_us)]
    coarse_step_us = max(int(plateau_coarse_step_us), int(step_us))
    decimated_coarse = []
    for delay_us in coarse_zone:
        if int(delay_us) == int(left_delay_us):
            decimated_coarse.append(int(delay_us))
            continue
        if ((int(delay_us) - int(left_delay_us)) % int(coarse_step_us)) == 0:
            decimated_coarse.append(int(delay_us))
    compressed_sequence = _sorted_unique_delays(decimated_coarse + dense_zone)

    if available_delay_slots is not None:
        essential_sequence = _sorted_unique_delays(
            [int(left_delay_us)] + [int(delay_us) for delay_us in dense_zone]
        )
        if int(len(essential_sequence)) > int(available_delay_slots):
            return {
                "delay_sequence": [],
                "requested_capture_count": int(requested_capture_count),
                "applied_capture_count": 0,
                "compressed": True,
            }
        if int(len(compressed_sequence)) > int(available_delay_slots):
            removable = [
                int(delay_us)
                for delay_us in compressed_sequence
                if int(delay_us) < int(dense_start_delay_us) and int(delay_us) != int(left_delay_us)
            ]
            trimmed = list(compressed_sequence)
            while int(len(trimmed)) > int(available_delay_slots) and removable:
                drop_delay_us = int(removable.pop(0))
                trimmed = [int(delay_us) for delay_us in trimmed if int(delay_us) != int(drop_delay_us)]
            compressed_sequence = _sorted_unique_delays(trimmed)

    applied_capture_count = int(len(compressed_sequence) * replicate_count)
    return {
        "delay_sequence": compressed_sequence,
        "requested_capture_count": int(requested_capture_count),
        "applied_capture_count": int(applied_capture_count),
        "compressed": True,
    }


def estimate_online_stream_tail_capture_requirements(
    *,
    scout_anchor_delay_us: int | None,
    scout_first_delay_us: int | None,
    scout_step_us: int,
    scout_replicates: int,
    max_scout_delay_count: int,
    backtrack_step_us: int,
    backtrack_replicates: int,
    fine_prepad_us: int,
    fine_postpad_us: int,
) -> dict:
    scout_anchor_delay = _to_int(scout_anchor_delay_us)
    scout_first_delay = _to_int(scout_first_delay_us)
    scout_step = max(1, _to_int(scout_step_us, DEFAULT_ONLINE_TAIL_POLICY["scout_step_us"]))
    scout_rep_count = max(1, _to_int(scout_replicates, 1))
    scout_delay_count = max(0, _to_int(max_scout_delay_count, 0))
    backtrack_step = max(1, _to_int(backtrack_step_us, DEFAULT_ONLINE_TAIL_POLICY["backtrack_step_us"]))
    backtrack_rep_count = max(1, _to_int(backtrack_replicates, 1))
    fine_prepad = max(0, _to_int(fine_prepad_us, DEFAULT_ONLINE_TAIL_POLICY["fine_prepad_us"]))
    fine_postpad = max(0, _to_int(fine_postpad_us, DEFAULT_ONLINE_TAIL_POLICY["fine_postpad_us"]))

    scout_capture_count = int(scout_delay_count * scout_rep_count)
    if scout_anchor_delay is None or scout_first_delay is None or scout_delay_count <= 0:
        return {
            "required_tail_capture_count": int(scout_capture_count),
            "required_tail_scout_capture_count": int(scout_capture_count),
            "required_tail_backtrack_capture_count": 0,
            "required_tail_left_extension_capture_count": 0,
            "minimum_tail_capture_count": int(scout_capture_count),
        }

    latest_landmark_delay_us = int(scout_first_delay + (max(0, scout_delay_count - 1) * scout_step))
    if int(scout_delay_count) > 1:
        initial_left_endpoint_delay_us = int(latest_landmark_delay_us - scout_step)
    else:
        initial_left_endpoint_delay_us = int(scout_anchor_delay)
    initial_left_endpoint_delay_us = max(int(scout_anchor_delay), int(initial_left_endpoint_delay_us))
    extended_left_endpoint_delay_us = max(
        int(scout_anchor_delay),
        int(initial_left_endpoint_delay_us) - int(scout_step),
    )

    initial_backtrack_sequence = build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=int(scout_anchor_delay),
        left_endpoint_delay_us=int(initial_left_endpoint_delay_us),
        landmark_delay_us=int(latest_landmark_delay_us),
        backtrack_step_us=int(backtrack_step),
        fine_prepad_us=int(fine_prepad),
        fine_postpad_us=int(fine_postpad),
    )
    extended_backtrack_sequence = build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=int(scout_anchor_delay),
        left_endpoint_delay_us=int(extended_left_endpoint_delay_us),
        landmark_delay_us=int(latest_landmark_delay_us),
        backtrack_step_us=int(backtrack_step),
        fine_prepad_us=int(fine_prepad),
        fine_postpad_us=int(fine_postpad),
    )
    minimum_backtrack = compress_online_stream_tail_backtrack_plan(
        delay_sequence=extended_backtrack_sequence,
        left_endpoint_delay_us=int(extended_left_endpoint_delay_us),
        landmark_delay_us=int(latest_landmark_delay_us),
        backtrack_step_us=int(backtrack_step),
        backtrack_replicates=int(backtrack_rep_count),
        fine_postpad_us=int(fine_postpad),
        force_compression=True,
    )
    initial_backtrack_capture_count = int(len(initial_backtrack_sequence) * backtrack_rep_count)
    left_extension_capture_count = int(
        max(0, len(extended_backtrack_sequence) - len(initial_backtrack_sequence))
        * int(backtrack_rep_count)
    )
    minimum_tail_capture_count = int(
        scout_capture_count + int(minimum_backtrack.get("applied_capture_count") or 0)
    )
    return {
        "required_tail_capture_count": int(
            scout_capture_count + initial_backtrack_capture_count + left_extension_capture_count
        ),
        "required_tail_scout_capture_count": int(scout_capture_count),
        "required_tail_backtrack_capture_count": int(initial_backtrack_capture_count),
        "required_tail_left_extension_capture_count": int(left_extension_capture_count),
        "minimum_tail_capture_count": int(minimum_tail_capture_count),
    }


def _find_delay_summary(summaries: list[dict], delay_us: int | None) -> dict | None:
    if delay_us is None:
        return None
    for row in list(summaries or []):
        summary = dict(row or {})
        if _to_int(summary.get("delay_us")) == int(delay_us):
            return summary
    return None


def _find_latest_accepted_flow_summary(
    summaries: list[dict] | None,
    *,
    max_delay_us: int | None,
) -> dict | None:
    latest_summary = None
    latest_delay_us = None
    max_delay_value = _to_int(max_delay_us)
    for row in list(summaries or []):
        summary = dict(row or {})
        delay_value = _to_int(summary.get("delay_us"))
        if delay_value is None:
            continue
        if max_delay_value is not None and int(delay_value) > int(max_delay_value):
            continue
        if not bool(summary.get("delay_accepted")):
            continue
        if _to_float_or_none(summary.get("median_width_px")) is None:
            continue
        if latest_delay_us is None or int(delay_value) >= int(latest_delay_us):
            latest_summary = summary
            latest_delay_us = int(delay_value)
    return None if latest_summary is None else dict(latest_summary)


def _summary_delay_from_emergence(summary: dict | None, delay_us: int | None) -> int | None:
    if summary:
        return _to_int(summary.get("delay_from_emergence_us"))
    return None


def _right_bracket_reason_for_summary(summary: dict | None) -> str | None:
    row = dict(summary or {})
    if bool(row.get("separated_from_nozzle_landmark")):
        return "separated_from_nozzle"
    if bool(row.get("attached_width_unavailable_landmark")):
        return "attached_width_unavailable"
    if bool(row.get("backup_width_collapse_landmark")):
        return "strong_width_collapse_backup"
    if bool(row.get("strong_tail_candidate")):
        return "strong_tail_transition"
    return None


def _confirmed_collapse_reason_for_summary(summary: dict | None) -> str | None:
    row = dict(summary or {})
    if bool(row.get("separated_from_nozzle_landmark")):
        return "separated_from_nozzle"
    if bool(row.get("attached_width_unavailable_landmark")):
        return "attached_width_unavailable"
    if bool(row.get("backup_width_collapse_landmark")):
        return "strong_width_collapse_backup"
    if bool(row.get("resolver_collapse_candidate")):
        return "confirmed_width_collapse"
    return None


def _trace_rows_in_delay_range(
    rows: list[dict] | None,
    *,
    start_delay_from_emergence_us: int | None = None,
    end_delay_from_emergence_us: int | None = None,
    require_width: bool = False,
) -> list[dict]:
    selected = []
    for item in list(rows or []):
        row = dict(item or {})
        delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if delay_from_emergence_us is None:
            continue
        if (
            start_delay_from_emergence_us is not None
            and int(delay_from_emergence_us) < int(start_delay_from_emergence_us)
        ):
            continue
        if (
            end_delay_from_emergence_us is not None
            and int(delay_from_emergence_us) > int(end_delay_from_emergence_us)
        ):
            continue
        width_px = _to_float_or_none(row.get("median_width_px"))
        if require_width and (not bool(row.get("tail_width_usable")) or width_px is None):
            continue
        row["median_width_px"] = width_px
        selected.append(row)
    selected.sort(key=lambda item: _to_int(item.get("delay_from_emergence_us"), 10**9))
    return selected


def _tail_settling_trace_window_end(
    rows: list[dict] | None,
    *,
    start_delay_from_emergence_us: int | None,
) -> int | None:
    candidates = _trace_rows_in_delay_range(
        rows,
        start_delay_from_emergence_us=start_delay_from_emergence_us,
        require_width=False,
    )
    if not candidates:
        return None
    for row in candidates:
        if bool(row.get("separated_from_nozzle_landmark")) or bool(
            row.get("attached_width_unavailable_landmark")
        ):
            return _to_int(row.get("delay_from_emergence_us"))
    usable_candidates = [
        _to_int(row.get("delay_from_emergence_us"))
        for row in candidates
        if bool(row.get("tail_width_usable")) and _to_float_or_none(row.get("median_width_px")) is not None
    ]
    if usable_candidates:
        return int(max(usable_candidates))
    return _to_int(candidates[-1].get("delay_from_emergence_us"))


def _odd_window_length(sample_count: int) -> int | None:
    if int(sample_count) < int(TAIL_SETTLING_MIN_SAVGOL_WINDOW):
        return None
    window = min(int(TAIL_SETTLING_MAX_SAVGOL_WINDOW), int(sample_count))
    if window % 2 == 0:
        window -= 1
    if window < int(TAIL_SETTLING_MIN_SAVGOL_WINDOW):
        return None
    return int(window)


def _savgol_or_passthrough(values: list[float]) -> tuple[list[float], int | None]:
    clean_values = [float(value) for value in list(values or [])]
    if not clean_values:
        return [], None
    window = _odd_window_length(len(clean_values))
    if window is None:
        return list(clean_values), None
    try:
        from scipy.signal import savgol_filter

        smoothed = savgol_filter(
            np.asarray(clean_values, dtype=float),
            window_length=int(window),
            polyorder=min(2, int(window) - 1),
            mode="interp",
        )
        return [float(value) for value in np.asarray(smoothed, dtype=float).tolist()], int(window)
    except Exception:
        return list(clean_values), None


def _resample_tail_width_trace(rows: list[dict] | None, *, step_us: int) -> list[dict]:
    usable_rows = _trace_rows_in_delay_range(rows, require_width=True)
    if len(usable_rows) < 2:
        return []
    delays = np.asarray(
        [_to_int(row.get("delay_from_emergence_us")) for row in usable_rows],
        dtype=float,
    )
    widths = np.asarray(
        [_to_float_or_none(row.get("median_width_px")) for row in usable_rows],
        dtype=float,
    )
    if len(delays) < 2 or float(delays[-1]) <= float(delays[0]):
        return []
    grid = np.arange(float(delays[0]), float(delays[-1]) + float(step_us), float(step_us), dtype=float)
    if len(grid) == 0 or float(grid[-1]) < float(delays[-1]):
        grid = np.append(grid, float(delays[-1]))
    else:
        grid[-1] = float(delays[-1])
    interpolated_widths = np.interp(grid, delays, widths)
    smoothed_widths, window_length = _savgol_or_passthrough(interpolated_widths.tolist())
    smoothed_array = np.asarray(smoothed_widths, dtype=float)
    if len(smoothed_array) != len(grid):
        smoothed_array = np.asarray(interpolated_widths, dtype=float)
        window_length = None
    if len(grid) >= 2:
        derivatives = np.gradient(smoothed_array, grid)
    else:
        derivatives = np.zeros_like(smoothed_array)
    samples = []
    for index, delay_from_emergence_us in enumerate(grid.tolist()):
        samples.append(
            {
                "delay_from_emergence_us": int(round(float(delay_from_emergence_us))),
                "interpolated_width_px": float(interpolated_widths[index]),
                "smoothed_width_px": float(smoothed_array[index]),
                "smoothed_width_derivative_px_per_us": float(derivatives[index]),
            }
        )
    return {
        "samples": samples,
        "window_length": window_length,
    }


def _tail_settling_candidate(
    *,
    local_trace: list[dict] | None,
    last_plateau_row: dict | None,
    initial_confirmed_collapse_delay_from_emergence_us: int | None,
) -> dict:
    diagnostics = {
        "tail_settling_candidate_delay_from_emergence_us": None,
        "tail_settling_trace_window_end_delay_from_emergence_us": None,
        "tail_settling_progress_threshold": float(TAIL_SETTLING_PROGRESS_THRESHOLD),
        "tail_settling_progress_window_length": None,
        "tail_settling_candidate_reason": "ineligible_missing_plateau",
    }
    plateau_delay_from_emergence_us = _to_int(
        None if last_plateau_row is None else last_plateau_row.get("delay_from_emergence_us")
    )
    plateau_width_px = _to_float_or_none(
        None if last_plateau_row is None else last_plateau_row.get("median_width_px")
    )
    if plateau_delay_from_emergence_us is None or plateau_width_px is None:
        return diagnostics

    trace_window_end_delay_from_emergence_us = _tail_settling_trace_window_end(
        local_trace,
        start_delay_from_emergence_us=plateau_delay_from_emergence_us,
    )
    if (
        trace_window_end_delay_from_emergence_us is not None
        and initial_confirmed_collapse_delay_from_emergence_us is not None
    ):
        trace_window_end_delay_from_emergence_us = min(
            int(trace_window_end_delay_from_emergence_us),
            int(initial_confirmed_collapse_delay_from_emergence_us),
        )
    diagnostics["tail_settling_trace_window_end_delay_from_emergence_us"] = (
        None
        if trace_window_end_delay_from_emergence_us is None
        else int(trace_window_end_delay_from_emergence_us)
    )
    if trace_window_end_delay_from_emergence_us is None:
        diagnostics["tail_settling_candidate_reason"] = "missing_extended_trace_window"
        return diagnostics

    usable_window_rows = _trace_rows_in_delay_range(
        local_trace,
        start_delay_from_emergence_us=plateau_delay_from_emergence_us,
        end_delay_from_emergence_us=trace_window_end_delay_from_emergence_us,
        require_width=True,
    )
    if len(usable_window_rows) < 2:
        diagnostics["tail_settling_candidate_reason"] = "insufficient_extended_width_trace"
        return diagnostics

    resampled = _resample_tail_width_trace(
        usable_window_rows,
        step_us=int(TAIL_SETTLING_INTERP_STEP_US),
    )
    samples = list(dict(resampled or {}).get("samples") or [])
    diagnostics["tail_settling_progress_window_length"] = dict(resampled or {}).get("window_length")
    if len(samples) < 2:
        diagnostics["tail_settling_candidate_reason"] = "insufficient_resampled_trace"
        return diagnostics

    min_smoothed_width_px = min(float(sample["smoothed_width_px"]) for sample in samples)
    total_drop_px = float(plateau_width_px) - float(min_smoothed_width_px)
    if total_drop_px <= 0.0:
        diagnostics["tail_settling_candidate_reason"] = "nonpositive_extended_drop"
        return diagnostics

    candidate_delay_from_emergence_us = None
    for sample in samples:
        progress = (
            float(plateau_width_px) - float(sample["smoothed_width_px"])
        ) / float(total_drop_px)
        progress = max(0.0, min(1.0, float(progress)))
        sample["collapse_progress"] = float(progress)
        if (
            candidate_delay_from_emergence_us is None
            and float(progress) >= float(TAIL_SETTLING_PROGRESS_THRESHOLD)
            and float(sample.get("smoothed_width_derivative_px_per_us") or 0.0) < 0.0
        ):
            candidate_delay_from_emergence_us = int(sample["delay_from_emergence_us"])

    diagnostics["tail_settling_candidate_delay_from_emergence_us"] = (
        None
        if candidate_delay_from_emergence_us is None
        else int(candidate_delay_from_emergence_us)
    )
    diagnostics["tail_settling_candidate_reason"] = (
        "progress_threshold_crossing"
        if candidate_delay_from_emergence_us is not None
        else "missing_progress_threshold_crossing"
    )
    return diagnostics


def select_online_stream_tail_left_anchor(
    *,
    scout_summaries: list[dict] | None,
    scout_anchor_delay_us: int | None,
    landmark_delay_us: int | None,
    policy: dict | None = None,
) -> dict:
    resolved_policy = _resolved_policy(policy)
    classified_scout_rows = _classify_trace_rows(list(scout_summaries or []), policy=resolved_policy)
    landmark_delay_value = _to_int(landmark_delay_us)
    prior_rows = [
        dict(row or {})
        for row in classified_scout_rows
        if landmark_delay_value is None
        or (
            _to_int(dict(row or {}).get("delay_us")) is not None
            and _to_int(dict(row or {}).get("delay_us")) < int(landmark_delay_value)
        )
    ]
    last_plateau_row = None
    for row in reversed(prior_rows):
        if bool(row.get("plateau_candidate")):
            last_plateau_row = dict(row)
            break
    if last_plateau_row is not None:
        return {
            "left_endpoint_delay_us": _to_int(last_plateau_row.get("delay_us")),
            "left_bracket_confirmed": True,
            "last_plateau_delay_us": _to_int(last_plateau_row.get("delay_us")),
        }
    prior_delays = [
        int(dict(row or {}).get("delay_us"))
        for row in prior_rows
        if _to_int(dict(row or {}).get("delay_us")) is not None
    ]
    if prior_delays:
        return {
            "left_endpoint_delay_us": max(prior_delays),
            "left_bracket_confirmed": False,
            "last_plateau_delay_us": None,
        }
    return {
        "left_endpoint_delay_us": _to_int(scout_anchor_delay_us),
        "left_bracket_confirmed": False,
        "last_plateau_delay_us": None,
    }


def _delay_from_emergence_from_plan(plan: dict | None, delay_us: int | None) -> int | None:
    resolved_plan = dict(plan or {})
    delay_value = _to_int(delay_us)
    scout_anchor_delay_us = _to_int(resolved_plan.get("scout_anchor_delay_us"))
    scout_anchor_delay_from_emergence_us = _to_int(
        resolved_plan.get("scout_anchor_delay_from_emergence_us")
    )
    if (
        delay_value is None
        or scout_anchor_delay_us is None
        or scout_anchor_delay_from_emergence_us is None
    ):
        return None
    return int(
        int(scout_anchor_delay_from_emergence_us)
        + int(delay_value)
        - int(scout_anchor_delay_us)
    )


def _legacy_tail_width_usable(row: dict) -> bool:
    qc = dict(row.get("qc") or {})
    if "tail_width_usable" in row:
        return bool(row.get("tail_width_usable"))
    if "tail_qc_pass" in row:
        return bool(row.get("tail_qc_pass"))
    if "tail_qc_pass" in qc:
        return bool(qc.get("tail_qc_pass"))
    return bool(str(row.get("status") or "") == "accepted" and row.get("attached_width_px") is not None)


def _legacy_tail_landmark_usable(row: dict) -> bool:
    if _attached_width_unavailable_landmark_row(row):
        return True
    if "tail_landmark_usable" in row:
        return bool(row.get("tail_landmark_usable"))
    return bool(row.get("separated_from_nozzle_landmark"))


def _attached_width_unavailable_landmark_row(row: dict) -> bool:
    summary = dict(row or {})
    if "attached_width_unavailable_landmark" in summary:
        return bool(summary.get("attached_width_unavailable_landmark"))
    qc = dict(summary.get("qc") or {})
    if bool(summary.get("tail_width_usable")) or bool(qc.get("tail_width_usable")):
        return False
    if summary.get("attached_width_px") is not None:
        return False
    warnings = list(summary.get("warnings") or [])
    if "attached_width_unavailable" in warnings:
        return True
    failure_reason = str(summary.get("failure_reason") or "").strip().lower()
    return "attached near-nozzle width unavailable" in failure_reason


def _width_ratio_to_baseline(width_px, baseline_width_px):
    width_value = _to_float_or_none(width_px)
    baseline_value = _to_float_or_none(baseline_width_px)
    if width_value in (None, 0.0) or baseline_value in (None, 0.0):
        return None
    return float(float(width_value) / float(baseline_value))


def _flow_anchor_summary(flow_summary: dict | None, baseline_width_px: float | int | None, *, phase_label: str):
    summary = dict(flow_summary or {})
    delay_us = _to_int(summary.get("delay_us"))
    delay_from_emergence_us = _to_int(summary.get("delay_from_emergence_us"))
    median_width_px = _to_float_or_none(summary.get("median_width_px"))
    width_ratio_to_baseline = _width_ratio_to_baseline(median_width_px, baseline_width_px)
    width_drop_from_baseline_px = None
    if median_width_px is not None and baseline_width_px is not None:
        width_drop_from_baseline_px = float(float(baseline_width_px) - float(median_width_px))
    delay_accepted = bool(summary.get("delay_accepted"))
    return {
        "phase": str(phase_label),
        "delay_us": delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "attempted_replicates": _to_int(summary.get("attempted_replicates"), 0),
        "accepted_replicates": _to_int(summary.get("accepted_replicates"), 0),
        "tail_width_usable_replicates": _to_int(summary.get("accepted_replicates"), 0),
        "tail_landmark_usable_replicates": 0,
        "rejected_replicates": _to_int(summary.get("rejected_replicates"), 0),
        "median_width_px": median_width_px,
        "width_ratio_to_baseline": width_ratio_to_baseline,
        "width_drop_from_baseline_px": width_drop_from_baseline_px,
        "tail_width_usable": bool(delay_accepted and median_width_px is not None),
        "tail_landmark_usable": False,
        "separated_from_nozzle_landmark": False,
        "attached_width_unavailable_landmark": False,
        "backup_width_collapse_landmark": False,
        "landmark_detected": False,
        "landmark_reason": None,
        "plateau_candidate": False,
        "early_departure_candidate": False,
        "strong_tail_candidate": False,
        "resolver_plateau_candidate": False,
        "resolver_transition_candidate": False,
        "resolver_collapse_candidate": False,
        "tail_affected": False,
        "tail_start_candidate": False,
        "attached_bottom_guard_hit": bool(summary.get("attached_bottom_guard_hit")),
        "detached_near_bottom_warning": bool(summary.get("detached_near_bottom_warning")),
        "near_nozzle_detached_warning": False,
        "late_frame_warning": False,
        "warnings": _copy_warnings(summary.get("warnings")),
        "delay_accepted": bool(delay_accepted),
        "triggered_scout": False,
        "triggered_backtrack": False,
        "triggered_coarse": False,
        "triggered_refine": False,
    }


def _classify_trace_rows(rows: list[dict], *, policy: dict | None = None) -> list[dict]:
    resolved_policy = _resolved_policy(policy)
    classified = []
    for row in list(rows or []):
        summary = dict(row or {})
        median_width_px = _to_float_or_none(summary.get("median_width_px"))
        width_ratio_to_baseline = _to_float_or_none(summary.get("width_ratio_to_baseline"))
        width_drop_from_baseline_px = _to_float_or_none(summary.get("width_drop_from_baseline_px"))
        if (
            width_drop_from_baseline_px is None
            and median_width_px is not None
            and width_ratio_to_baseline is not None
            and float(width_ratio_to_baseline) > 0.0
        ):
            inferred_baseline_px = float(float(median_width_px) / float(width_ratio_to_baseline))
            width_drop_from_baseline_px = float(inferred_baseline_px - float(median_width_px))
        summary_for_thresholds = {
            **summary,
            "median_width_px": median_width_px,
            "width_ratio_to_baseline": width_ratio_to_baseline,
            "width_drop_from_baseline_px": width_drop_from_baseline_px,
        }
        transition_width_drop_threshold_px = _material_width_drop_threshold_px(
            summary_for_thresholds,
            resolved_policy,
            px_key="resolver_transition_width_drop_px",
            frac_key="resolver_transition_width_drop_frac",
        )
        collapse_width_drop_threshold_px = _material_width_drop_threshold_px(
            summary_for_thresholds,
            resolved_policy,
            px_key="resolver_collapse_width_drop_px",
            frac_key="resolver_collapse_width_drop_frac",
        )
        tail_width_usable = bool(summary.get("tail_width_usable"))
        separated_from_nozzle_landmark = bool(summary.get("separated_from_nozzle_landmark"))
        attached_width_unavailable_landmark = bool(summary.get("attached_width_unavailable_landmark"))
        backup_width_collapse_landmark = bool(summary.get("backup_width_collapse_landmark"))
        plateau_candidate = bool(
            tail_width_usable
            and width_ratio_to_baseline is not None
            and float(width_ratio_to_baseline) >= float(resolved_policy["plateau_width_frac"])
            and not separated_from_nozzle_landmark
            and not attached_width_unavailable_landmark
        )
        early_departure_candidate = bool(
            tail_width_usable
            and width_ratio_to_baseline is not None
            and float(resolved_policy["departure_width_frac"]) <= float(width_ratio_to_baseline) < float(resolved_policy["plateau_width_frac"])
            and not separated_from_nozzle_landmark
            and not attached_width_unavailable_landmark
        )
        strong_tail_candidate = bool(
            (tail_width_usable and width_ratio_to_baseline is not None and float(width_ratio_to_baseline) < float(resolved_policy["departure_width_frac"]))
            or separated_from_nozzle_landmark
            or attached_width_unavailable_landmark
            or backup_width_collapse_landmark
        )
        resolver_plateau_candidate = bool(
            tail_width_usable
            and width_drop_from_baseline_px is not None
            and float(width_drop_from_baseline_px) < float(resolved_policy["resolver_plateau_width_drop_px"])
            and not separated_from_nozzle_landmark
            and not attached_width_unavailable_landmark
        )
        resolver_transition_candidate = bool(
            tail_width_usable
            and width_drop_from_baseline_px is not None
            and float(width_drop_from_baseline_px) >= float(transition_width_drop_threshold_px)
            and float(width_drop_from_baseline_px) < float(collapse_width_drop_threshold_px)
            and not separated_from_nozzle_landmark
            and not attached_width_unavailable_landmark
        )
        resolver_collapse_candidate = bool(
            (
                tail_width_usable
                and (
                    (
                        width_drop_from_baseline_px is not None
                        and float(width_drop_from_baseline_px) >= float(collapse_width_drop_threshold_px)
                    )
                    or (
                        width_ratio_to_baseline is not None
                        and float(width_ratio_to_baseline) <= float(resolved_policy["resolver_collapse_width_frac"])
                    )
                )
            )
            or separated_from_nozzle_landmark
            or attached_width_unavailable_landmark
            or backup_width_collapse_landmark
        )
        summary["width_drop_from_baseline_px"] = width_drop_from_baseline_px
        summary["resolver_transition_width_drop_threshold_px"] = float(transition_width_drop_threshold_px)
        summary["resolver_collapse_width_drop_threshold_px"] = float(collapse_width_drop_threshold_px)
        summary["plateau_candidate"] = bool(plateau_candidate)
        summary["early_departure_candidate"] = bool(early_departure_candidate)
        summary["strong_tail_candidate"] = bool(strong_tail_candidate)
        summary["resolver_plateau_candidate"] = bool(resolver_plateau_candidate)
        summary["resolver_transition_candidate"] = bool(resolver_transition_candidate)
        summary["resolver_collapse_candidate"] = bool(resolver_collapse_candidate)
        summary["tail_affected"] = bool(strong_tail_candidate)
        summary["tail_start_candidate"] = bool(early_departure_candidate or strong_tail_candidate)
        classified.append(summary)
    classified.sort(
        key=lambda item: (
            _to_int(item.get("delay_from_emergence_us"), 10**9),
            _to_int(item.get("delay_us"), 10**9),
        )
    )
    return classified


def plan_online_stream_tail_phase(
    *,
    flow_fit_result: dict | None,
    priors: dict | None,
    emergence_time_us: int,
    capture_budget: dict | None,
    flow_delay_summaries: list[dict] | None = None,
    policy: dict | None = None,
    analysis_config: dict | None = None,
) -> dict:
    fit = dict(flow_fit_result or {})
    normalized_priors = online_cal_mod.normalize_online_stream_prior(priors)
    resolved_policy = _resolved_policy(policy)
    resolved_analysis_config = _resolved_analysis_config(analysis_config)
    steady_width_baseline_px = _to_float_or_none(fit.get("steady_width_baseline_px"))
    fit_status = str(fit.get("fit_status") or "")
    if steady_width_baseline_px is None or fit_status.startswith("unresolved"):
        return {
            "run_tail": False,
            "skip_reason": "missing_flow_baseline",
            "analysis_config": _copy_jsonish(resolved_analysis_config),
            "steady_width_baseline_px": steady_width_baseline_px,
            "tail_retarget_count": 0,
            "retargeted_coarse_start_delay_us": None,
        }

    accepted_flow_summaries = [
        dict(row or {})
        for row in list(flow_delay_summaries or [])
        if bool(dict(row or {}).get("delay_accepted")) and _to_int(dict(row or {}).get("delay_us")) is not None
    ]
    if not accepted_flow_summaries:
        return {
            "run_tail": False,
            "skip_reason": "missing_flow_tail_anchor",
            "analysis_config": _copy_jsonish(resolved_analysis_config),
            "steady_width_baseline_px": float(steady_width_baseline_px),
            "tail_retarget_count": 0,
            "retargeted_coarse_start_delay_us": None,
        }

    accepted_flow_summaries.sort(key=lambda item: _to_int(item.get("delay_us"), 0))
    last_flow_summary = dict(accepted_flow_summaries[-1])
    last_flow_delay_us = int(_to_int(last_flow_summary.get("delay_us"), 0))
    last_flow_delay_from_emergence_us = int(
        _to_int(last_flow_summary.get("delay_from_emergence_us"), int(last_flow_delay_us) - int(emergence_time_us))
    )
    scout_step_us = int(resolved_policy["scout_step_us"])
    scout_replicates = int(resolved_policy["scout_replicates"])
    max_scout_delay_count = int(resolved_policy["max_scout_delay_count"])
    backtrack_step_us = int(resolved_policy["backtrack_step_us"])
    backtrack_replicates = int(resolved_policy["backtrack_replicates"])
    fine_prepad_us = int(resolved_policy["fine_prepad_us"])
    fine_postpad_us = int(resolved_policy["fine_postpad_us"])
    reserved_backtrack_capture_count = int(resolved_policy["reserved_backtrack_capture_count"])
    scout_first_delay_us = int(last_flow_delay_us + scout_step_us)
    scout_first_delay_from_emergence_us = int(last_flow_delay_from_emergence_us + scout_step_us)
    budget_requirements = estimate_online_stream_tail_capture_requirements(
        scout_anchor_delay_us=int(last_flow_delay_us),
        scout_first_delay_us=int(scout_first_delay_us),
        scout_step_us=int(scout_step_us),
        scout_replicates=int(scout_replicates),
        max_scout_delay_count=int(max_scout_delay_count),
        backtrack_step_us=int(backtrack_step_us),
        backtrack_replicates=int(backtrack_replicates),
        fine_prepad_us=int(fine_prepad_us),
        fine_postpad_us=int(fine_postpad_us),
    )
    remaining_hard = _remaining_hard_budget(capture_budget)
    minimum_tail_capture_count = int(
        budget_requirements.get("minimum_tail_capture_count")
        or budget_requirements.get("required_tail_capture_count")
        or 0
    )
    if remaining_hard < int(minimum_tail_capture_count):
        return {
            "run_tail": False,
            "skip_reason": "capture_budget_exhausted",
            "analysis_config": _copy_jsonish(resolved_analysis_config),
            "steady_width_baseline_px": float(steady_width_baseline_px),
            "search_method": SEARCH_METHOD,
            "planned_scout_delay_count": int(max_scout_delay_count),
            "max_scout_delay_count": int(max_scout_delay_count),
            "reserved_backtrack_capture_count": int(reserved_backtrack_capture_count),
            "fine_prepad_us": int(fine_prepad_us),
            "fine_postpad_us": int(fine_postpad_us),
            "required_capture_count": int(budget_requirements["required_tail_capture_count"]),
            "required_tail_capture_count": int(budget_requirements["required_tail_capture_count"]),
            "required_tail_scout_capture_count": int(
                budget_requirements["required_tail_scout_capture_count"]
            ),
            "required_tail_backtrack_capture_count": int(
                budget_requirements["required_tail_backtrack_capture_count"]
            ),
            "required_tail_left_extension_capture_count": int(
                budget_requirements["required_tail_left_extension_capture_count"]
            ),
            "tail_backtrack_compressed": False,
            "tail_backtrack_requested_capture_count": None,
            "tail_backtrack_applied_capture_count": None,
            "tail_retarget_count": 0,
            "retargeted_coarse_start_delay_us": None,
        }
    planned_scout_delay_count = int(max(0, max_scout_delay_count))

    return {
        "run_tail": True,
        "skip_reason": None,
        "search_method": SEARCH_METHOD,
        "analysis_config": _copy_jsonish(resolved_analysis_config),
        "steady_width_baseline_px": float(steady_width_baseline_px),
        "plan_source": "last_flow_delay_anchor",
        "prior_condition_match": str(normalized_priors.get("condition_match") or "none"),
        "recorded_tail_start_offset_us": _to_int(normalized_priors.get("tail_start_offset_us")),
        "recorded_tail_coarse_step_us": _to_int(normalized_priors.get("tail_coarse_step_us")),
        "scout_anchor_delay_us": int(last_flow_delay_us),
        "scout_anchor_delay_from_emergence_us": int(last_flow_delay_from_emergence_us),
        "scout_first_delay_us": int(scout_first_delay_us),
        "scout_first_delay_from_emergence_us": int(scout_first_delay_from_emergence_us),
        "scout_step_us": int(scout_step_us),
        "scout_replicates": int(scout_replicates),
        "max_scout_delay_count": int(max_scout_delay_count),
        "backtrack_step_us": int(backtrack_step_us),
        "backtrack_replicates": int(backtrack_replicates),
        "fine_prepad_us": int(fine_prepad_us),
        "fine_postpad_us": int(fine_postpad_us),
        "planned_scout_delay_count": int(planned_scout_delay_count),
        "reserved_backtrack_capture_count": int(reserved_backtrack_capture_count),
        "required_tail_capture_count": int(budget_requirements["required_tail_capture_count"]),
        "required_tail_scout_capture_count": int(
            budget_requirements["required_tail_scout_capture_count"]
        ),
        "required_tail_backtrack_capture_count": int(
            budget_requirements["required_tail_backtrack_capture_count"]
        ),
        "required_tail_left_extension_capture_count": int(
            budget_requirements["required_tail_left_extension_capture_count"]
        ),
        "tail_backtrack_compressed": False,
        "tail_backtrack_requested_capture_count": None,
        "tail_backtrack_applied_capture_count": None,
        "tail_retarget_count": 0,
        "retargeted_coarse_start_delay_us": None,
        "coarse_start_delay_us": int(scout_first_delay_us),
        "coarse_step_us": int(scout_step_us),
        "coarse_replicates": int(scout_replicates),
        "refine_step_us": int(backtrack_step_us),
        "refine_replicates": int(backtrack_replicates),
        "planned_coarse_delay_count": int(planned_scout_delay_count),
        "reserved_refine_delay_count": int(reserved_backtrack_capture_count),
        "reserved_refine_capture_count": int(reserved_backtrack_capture_count),
    }


def summarize_online_stream_tail_delay(
    frame_rows: list[dict],
    baseline_width_px: float | int | None,
    *,
    policy: dict | None = None,
) -> dict:
    rows = [dict(row or {}) for row in list(frame_rows or [])]
    width_usable_rows = [row for row in rows if _legacy_tail_width_usable(row)]
    landmark_usable_rows = [row for row in rows if _legacy_tail_landmark_usable(row)]
    usable_rows = [
        row
        for row in rows
        if _legacy_tail_width_usable(row) or _legacy_tail_landmark_usable(row)
    ]
    attempted_replicates = int(len(rows))
    accepted_replicates = int(len(usable_rows))
    width_usable_replicates = int(len(width_usable_rows))
    landmark_usable_replicates = int(len(landmark_usable_rows))
    rejected_replicates = int(max(0, attempted_replicates - accepted_replicates))
    median_width_px = _median_or_none(row.get("attached_width_px") for row in width_usable_rows)
    width_ratio_to_baseline = _width_ratio_to_baseline(median_width_px, baseline_width_px)
    resolved_policy = _resolved_policy(policy)
    warnings = _unique_strings(
        warning
        for row in rows
        for warning in list(row.get("warnings") or [])
    )
    attached_bottom_guard_hit = any(
        str(row.get("status") or "") == "rejected_bottom_guard"
        or bool(row.get("attached_bottom_guard_hit"))
        or ("attached_bottom_guard_hit" in list(row.get("warnings") or []))
        for row in rows
    )
    detached_near_bottom_warning = any(
        bool(row.get("detached_near_bottom_warning"))
        or ("detached_near_bottom_warning" in list(row.get("warnings") or []))
        for row in rows
    )
    near_nozzle_detached_warning = any(
        bool(row.get("near_nozzle_detached_warning"))
        or ("near_nozzle_detached_warning" in list(row.get("warnings") or []))
        for row in rows
    )
    attached_width_unavailable_landmark = any(
        _attached_width_unavailable_landmark_row(row)
        for row in rows
    )
    late_frame_warning = bool(
        any(bool(row.get("late_frame_warning")) for row in rows)
        or attached_bottom_guard_hit
        or detached_near_bottom_warning
    )
    separated_from_nozzle_landmark = any(
        bool(row.get("separated_from_nozzle_landmark"))
        for row in rows
    )
    phase_label = str((rows[0] if rows else {}).get("phase") or "")
    backup_width_collapse_landmark = bool(
        width_usable_replicates > 0
        and width_ratio_to_baseline is not None
        and float(width_ratio_to_baseline) <= float(resolved_policy["scout_landmark_width_frac"])
        and not separated_from_nozzle_landmark
        and not attached_width_unavailable_landmark
        and phase_label not in {"tail_backtrack", "tail_refine", "refine"}
    )
    landmark_detected = bool(
        separated_from_nozzle_landmark
        or attached_width_unavailable_landmark
        or backup_width_collapse_landmark
    )
    landmark_reason = None
    if separated_from_nozzle_landmark:
        landmark_reason = "separated_from_nozzle"
    elif attached_width_unavailable_landmark:
        landmark_reason = "attached_width_unavailable"
    elif backup_width_collapse_landmark:
        landmark_reason = "strong_width_collapse_backup"

    delay_us = None
    delay_from_emergence_us = None
    phase = None
    if rows:
        delay_us = _to_int(rows[0].get("delay_us"))
        delay_from_emergence_us = _to_int(rows[0].get("delay_from_emergence_us"))
        phase = phase_label

    summary = {
        "phase": phase,
        "delay_us": delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "attempted_replicates": int(attempted_replicates),
        "accepted_replicates": int(accepted_replicates),
        "tail_width_usable_replicates": int(width_usable_replicates),
        "tail_landmark_usable_replicates": int(landmark_usable_replicates),
        "rejected_replicates": int(rejected_replicates),
        "median_width_px": median_width_px,
        "width_ratio_to_baseline": width_ratio_to_baseline,
        "width_drop_from_baseline_px": (
            None
            if median_width_px is None or baseline_width_px is None
            else float(float(baseline_width_px) - float(median_width_px))
        ),
        "tail_width_usable": bool(width_usable_replicates > 0),
        "tail_landmark_usable": bool(landmark_usable_replicates > 0),
        "separated_from_nozzle_landmark": bool(separated_from_nozzle_landmark),
        "attached_width_unavailable_landmark": bool(attached_width_unavailable_landmark),
        "backup_width_collapse_landmark": bool(backup_width_collapse_landmark),
        "landmark_detected": bool(landmark_detected),
        "landmark_reason": landmark_reason,
        "attached_bottom_guard_hit": bool(attached_bottom_guard_hit),
        "detached_near_bottom_warning": bool(detached_near_bottom_warning),
        "near_nozzle_detached_warning": bool(near_nozzle_detached_warning),
        "late_frame_warning": bool(late_frame_warning),
        "warnings": warnings,
        "delay_accepted": bool(accepted_replicates > 0),
        "triggered_scout": bool(landmark_detected),
        "triggered_backtrack": False,
        "triggered_coarse": bool(landmark_detected),
        "triggered_refine": False,
    }
    classified = _classify_trace_rows([summary], policy=resolved_policy)
    if classified:
        summary.update(classified[0])
    return summary


def build_online_stream_tail_backtrack_plan(
    *,
    scout_anchor_delay_us: int | None = None,
    left_endpoint_delay_us: int | None,
    landmark_delay_us: int | None,
    backtrack_step_us: int,
    fine_prepad_us: int | None = None,
    fine_postpad_us: int | None = None,
) -> list[int]:
    scout_anchor_delay = _to_int(scout_anchor_delay_us)
    left_delay_us = _to_int(left_endpoint_delay_us)
    right_delay_us = _to_int(landmark_delay_us)
    step_us = max(1, _to_int(backtrack_step_us, DEFAULT_ONLINE_TAIL_POLICY["backtrack_step_us"]))
    prepad_us = max(0, _to_int(fine_prepad_us, DEFAULT_ONLINE_TAIL_POLICY["fine_prepad_us"]))
    postpad_us = max(0, _to_int(fine_postpad_us, DEFAULT_ONLINE_TAIL_POLICY["fine_postpad_us"]))
    if left_delay_us is None or right_delay_us is None or int(left_delay_us) > int(right_delay_us):
        return []
    start_delay_us = int(left_delay_us) - int(prepad_us)
    if scout_anchor_delay is not None:
        start_delay_us = max(int(scout_anchor_delay), int(start_delay_us))
    end_delay_us = int(right_delay_us) + int(postpad_us)
    if int(start_delay_us) > int(end_delay_us):
        return []
    return [
        int(delay_us)
        for delay_us in range(int(start_delay_us), int(end_delay_us) + int(step_us), int(step_us))
    ]


def build_online_stream_tail_refine_plan(
    *,
    last_coarse_nontrigger_delay_us: int | None,
    first_coarse_trigger_delay_us: int | None,
    refine_step_us: int,
    coarse_step_us: int | None = None,
    planned_coarse_start_delay_us: int | None = None,
) -> list[int]:
    del coarse_step_us, planned_coarse_start_delay_us
    return build_online_stream_tail_backtrack_plan(
        left_endpoint_delay_us=last_coarse_nontrigger_delay_us,
        landmark_delay_us=first_coarse_trigger_delay_us,
        backtrack_step_us=refine_step_us,
        fine_prepad_us=0,
        fine_postpad_us=0,
    )


def decide_online_stream_tail_next_action(
    *,
    mode: str,
    delay_summary: dict | None,
    capture_budget: dict | None,
    consecutive_failed_delays: int = 0,
    attempted_delay_count: int = 0,
    planned_delay_count: int = 0,
    scout_summaries: list[dict] | None = None,
    policy: dict | None = None,
    **unused,
) -> dict:
    del unused
    summary = dict(delay_summary or {})
    budget = dict(capture_budget or {})
    resolved_policy = _resolved_policy(policy)
    mode_label = str(mode or "scout")
    if mode_label == "coarse":
        mode_label = "scout"
    if mode_label == "refine":
        mode_label = "backtrack"

    if mode_label == "scout":
        if bool(summary.get("landmark_detected")):
            if _is_backup_width_collapse_landmark(summary):
                confirmation = _backup_landmark_confirmation(
                    delay_summary=summary,
                    scout_summaries=scout_summaries,
                    attempted_delay_count=int(attempted_delay_count),
                    planned_delay_count=int(planned_delay_count),
                    resolved_policy=resolved_policy,
                )
                if not bool(confirmation.get("confirmed")):
                    return {
                        "action": "continue",
                        "tail_phase_status": None,
                        "termination_reason": None,
                        "warnings": _copy_warnings(confirmation.get("warnings")),
                        "tail_backup_landmark_confirmed": False,
                        "tail_backup_landmark_confirmation_reason": str(
                            confirmation.get("reason") or ""
                        ),
                    }
                return {
                    "action": "switch_to_backtrack",
                    "tail_phase_status": None,
                    "termination_reason": None,
                    "landmark_reason": str(summary.get("landmark_reason") or ""),
                    "warnings": _copy_warnings(confirmation.get("warnings")),
                    "tail_backup_landmark_confirmed": True,
                    "tail_backup_landmark_confirmation_reason": str(
                        confirmation.get("reason") or ""
                    ),
                }
            return {
                "action": "switch_to_backtrack",
                "tail_phase_status": None,
                "termination_reason": None,
                "landmark_reason": str(summary.get("landmark_reason") or ""),
                "warnings": [],
                "tail_backup_landmark_confirmed": False,
                "tail_backup_landmark_confirmation_reason": None,
            }
        if int(consecutive_failed_delays) >= int(resolved_policy["consecutive_failed_tail_delays_stop"]):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_qc_failure",
                "termination_reason": "repeated_tail_qc_failure",
            }
        if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_no_landmark",
                "termination_reason": "no_scout_landmark",
            }
        if bool(budget.get("exhausted")):
            return {
                "action": "stop",
                "tail_phase_status": "unresolved_budget_exhausted",
                "termination_reason": "capture_budget_exhausted",
            }
        return {
            "action": "continue",
            "tail_phase_status": None,
            "termination_reason": None,
        }

    if int(consecutive_failed_delays) >= int(resolved_policy["consecutive_failed_tail_delays_stop"]):
        return {
            "action": "stop",
            "tail_phase_status": "unresolved_qc_failure",
            "termination_reason": "repeated_tail_qc_failure",
        }
    if bool(budget.get("exhausted")):
        return {
            "action": "stop",
            "tail_phase_status": "unresolved_budget_exhausted",
            "termination_reason": "capture_budget_exhausted",
        }
    if int(attempted_delay_count) >= int(max(0, planned_delay_count)):
        return {
            "action": "finish_resolve",
            "tail_phase_status": None,
            "termination_reason": None,
        }
    return {
        "action": "continue",
        "tail_phase_status": None,
        "termination_reason": None,
    }


def _tail_right_edge_coverage_summary(
    backtrack_rows: list[dict] | None,
    *,
    policy: dict | None = None,
) -> dict:
    resolved_policy = _resolved_policy(policy)
    classified_rows = _classify_trace_rows(list(backtrack_rows or []), policy=resolved_policy)
    width_rows = [
        dict(row or {})
        for row in classified_rows
        if bool(row.get("tail_width_usable"))
        and _to_float_or_none(row.get("median_width_px")) is not None
        and _to_int(row.get("delay_us")) is not None
    ]
    width_rows.sort(key=lambda item: int(_to_int(item.get("delay_us"), 0)))
    selection_noise_floor_px = None
    if width_rows:
        selection_noise_floor_px = _material_width_drop_threshold_px(
            width_rows[0],
            resolved_policy,
            px_key="resolver_transition_width_drop_px",
            frac_key="resolver_transition_width_drop_frac",
        )

    diagnostics = {
        "tail_collapse_coverage_ok": True,
        "tail_right_extension_needed": False,
        "tail_right_extension_reason": None,
        "tail_min_width_delay_from_emergence_us": None,
        "tail_min_width_at_right_edge": False,
        "tail_width_still_falling_at_right_edge": False,
        "tail_selection_noise_floor_px": (
            None if selection_noise_floor_px is None else float(selection_noise_floor_px)
        ),
    }
    if len(width_rows) < 2:
        return diagnostics

    min_index = min(
        range(len(width_rows)),
        key=lambda index: float(_to_float_or_none(width_rows[index].get("median_width_px"))),
    )
    min_row = dict(width_rows[min_index])
    min_width_px = _to_float_or_none(min_row.get("median_width_px"))
    diagnostics["tail_min_width_delay_from_emergence_us"] = _to_int(
        min_row.get("delay_from_emergence_us")
    )
    min_delay_us = _to_int(min_row.get("delay_us"))
    min_at_right_edge = bool(min_index >= len(width_rows) - 2)
    diagnostics["tail_min_width_at_right_edge"] = bool(min_at_right_edge)

    still_falling = False
    if min_index > 0 and min_width_px is not None:
        previous_width_px = _to_float_or_none(width_rows[min_index - 1].get("median_width_px"))
        if previous_width_px is not None:
            still_falling = bool(
                float(previous_width_px) - float(min_width_px)
                >= float(resolved_policy["tail_right_extension_min_falling_drop_px"])
            )
    diagnostics["tail_width_still_falling_at_right_edge"] = bool(still_falling)

    terminal_after_min = False
    recovered_after_min = False
    if min_delay_us is not None:
        for row in classified_rows:
            row_delay_us = _to_int(row.get("delay_us"))
            if row_delay_us is None or int(row_delay_us) <= int(min_delay_us):
                continue
            if (
                bool(row.get("separated_from_nozzle_landmark"))
                or bool(row.get("attached_width_unavailable_landmark"))
                or not bool(row.get("tail_width_usable"))
            ):
                terminal_after_min = True
                break
            later_width_px = _to_float_or_none(row.get("median_width_px"))
            if min_width_px is not None and later_width_px is not None and float(later_width_px) >= float(min_width_px):
                recovered_after_min = True

    raw_extension_needed = bool(
        min_at_right_edge and still_falling and not terminal_after_min and not recovered_after_min
    )
    diagnostics["tail_collapse_coverage_ok"] = not bool(raw_extension_needed)
    diagnostics["tail_right_extension_needed"] = bool(
        raw_extension_needed and bool(resolved_policy["tail_right_extension_enabled"])
    )
    if raw_extension_needed:
        diagnostics["tail_right_extension_reason"] = "right_edge_width_still_falling"
    return diagnostics


def decide_online_stream_tail_right_extension(
    *,
    resolve_result: dict | None,
    tail_plan: dict | None,
    backtrack_summaries: list[dict] | None,
    capture_budget: dict | None,
    replicates_per_delay: int = 1,
    policy: dict | None = None,
) -> dict:
    plan = dict(tail_plan or {})
    plan_policy = plan.get("policy") if isinstance(plan.get("policy"), dict) else None
    resolved_policy = _resolved_policy(policy or plan_policy)
    tail_phase = dict((dict(resolve_result or {}).get("tail_phase") or {}))
    if not bool(resolved_policy["tail_right_extension_enabled"]):
        return {"extend": False, "reason": "disabled", "warning": None, "next_delay_us": None}
    if not bool(tail_phase.get("tail_right_extension_needed")):
        return {"extend": False, "reason": "not_needed", "warning": None, "next_delay_us": None}

    step_us = max(1, _to_int(plan.get("backtrack_step_us"), resolved_policy["backtrack_step_us"]))
    max_extension_us = max(0, _to_int(resolved_policy.get("tail_right_extension_max_us"), 0))
    max_extension_count = int(max_extension_us // int(step_us)) if step_us > 0 else 0
    extension_count = max(0, _to_int(plan.get("tail_right_extension_count"), 0))
    if extension_count >= max_extension_count:
        return {
            "extend": False,
            "reason": "max_reached",
            "warning": "tail_right_extension_max_reached",
            "next_delay_us": None,
        }

    required_captures = max(1, _to_int(replicates_per_delay, 1))
    if _remaining_hard_budget(capture_budget) < int(required_captures):
        return {
            "extend": False,
            "reason": "budget_exhausted",
            "warning": "tail_right_extension_budget_exhausted",
            "next_delay_us": None,
        }

    sampled_delays = _sorted_unique_delays(
        row.get("delay_us") for row in list(backtrack_summaries or [])
    )
    if not sampled_delays:
        return {"extend": False, "reason": "missing_backtrack_delays", "warning": None, "next_delay_us": None}
    return {
        "extend": True,
        "reason": str(tail_phase.get("tail_right_extension_reason") or "right_edge_width_still_falling"),
        "warning": None,
        "next_delay_us": int(max(sampled_delays) + int(step_us)),
    }


def _segmented_tail_source_rows(
    scout_summaries: list[dict] | None,
    backtrack_summaries: list[dict] | None,
) -> list[dict]:
    rows = []
    for row in list(scout_summaries or []) + list(backtrack_summaries or []):
        summary = dict(row or {})
        delay_from_emergence_us = _to_int(summary.get("delay_from_emergence_us"))
        if delay_from_emergence_us is None:
            continue
        width_px = _to_float_or_none(summary.get("median_width_px"))
        rows.append(
            {
                "phase": str(summary.get("phase") or ""),
                "status": "accepted" if bool(summary.get("tail_width_usable")) else "rejected",
                "delay_us": _to_int(summary.get("delay_us")),
                "delay_from_emergence_us": int(delay_from_emergence_us),
                "attached_width_px": None if width_px is None else float(width_px),
                "tail_width_usable": bool(summary.get("tail_width_usable")) and width_px is not None,
            }
        )
    return rows


def _segmented_tail_confidence(result: dict) -> str:
    if segmented_tail_mod is None:
        return "unavailable"
    tail_start = _to_int(result.get("tail_start_delay_from_emergence_us"))
    if str(result.get("fit_status") or "") != "ok" or tail_start is None:
        return "unavailable"
    source = str(result.get("tail_start_source") or "")
    model_name = str(result.get("model_name") or "")
    if source == segmented_tail_mod.TAIL_START_SOURCE_THREE_BREAK_TAU1:
        local_confirmation = dict(result.get("local_confirmation") or {})
        return "high" if bool(local_confirmation.get("passed", True)) else "medium"
    if source == segmented_tail_mod.TAIL_START_SOURCE_THREE_TWO_MIDPOINT:
        return "medium"
    if model_name in {
        segmented_tail_mod.MODEL_PLATEAU_DECLINE,
        segmented_tail_mod.MODEL_PLATEAU_SHOULDER_COLLAPSE,
    }:
        return "low"
    return "unavailable"


def _compact_segmented_tail_shadow_payload(
    result: dict,
    *,
    runtime_tail_start_delay_from_emergence_us: int | None,
) -> dict:
    tail_start = _to_int(result.get("tail_start_delay_from_emergence_us"))
    runtime_tail_start = _to_int(runtime_tail_start_delay_from_emergence_us)
    delta_from_runtime = None
    if tail_start is not None and runtime_tail_start is not None:
        delta_from_runtime = int(tail_start) - int(runtime_tail_start)
    fit_status = str(result.get("fit_status") or "unknown")
    status = fit_status
    if fit_status == "ok" and tail_start is None:
        status = "no_tail_start"
    return {
        "status": status,
        "fit_status": fit_status,
        "model_name": result.get("model_name"),
        "tail_start_source": result.get("tail_start_source"),
        "confidence": _segmented_tail_confidence(result),
        "tail_start_delay_from_emergence_us": tail_start,
        "tail_start_delta_from_runtime_us": delta_from_runtime,
        "runtime_tail_start_delay_from_emergence_us": runtime_tail_start,
        "knee_delay_from_emergence_us": _to_int(result.get("knee_delay_from_emergence_us")),
        "second_knee_delay_from_emergence_us": _to_int(result.get("second_knee_delay_from_emergence_us")),
        "breakpoint_delays_from_emergence_us": _copy_jsonish(
            result.get("breakpoint_delays_from_emergence_us") or []
        ),
        "breakpoint_observed_delays": _copy_jsonish(result.get("breakpoint_observed_delays") or []),
        "three_break_tail_start_delay_from_emergence_us": _to_int(
            result.get("three_break_tail_start_delay_from_emergence_us")
        ),
        "two_break_tail_start_delay_from_emergence_us": _to_int(
            result.get("two_break_tail_start_delay_from_emergence_us")
        ),
        "midpoint_tail_start_delay_from_emergence_us": _to_int(
            result.get("midpoint_tail_start_delay_from_emergence_us")
        ),
        "tail_start_observed_delay": result.get("tail_start_observed_delay"),
        "breakpoint_refinement_step_us": _to_int(result.get("breakpoint_refinement_step_us")),
        "usable_point_count": _to_int(result.get("usable_point_count"), 0),
        "noise_estimate_px": _to_float_or_none(result.get("noise_estimate_px")),
        "bic_scores": _copy_jsonish(result.get("bic_scores") or {}),
        "local_confirmation": _copy_jsonish(result.get("local_confirmation") or {}),
        "three_break_selection_gate": _copy_jsonish(result.get("three_break_selection_gate") or {}),
        "trace": _copy_jsonish(result.get("trace") or []),
        "fit_points": _copy_jsonish(result.get("fit_points") or []),
    }


def evaluate_online_stream_segmented_tail_shadow(
    *,
    scout_summaries: list[dict] | None,
    backtrack_summaries: list[dict] | None,
    baseline_width_px: float | int | None,
    runtime_tail_start_delay_from_emergence_us: int | None = None,
    analysis_config: dict | None = None,
) -> dict | None:
    resolved_analysis_config = _resolved_analysis_config(analysis_config)
    if not bool(resolved_analysis_config.get("segmented_tail_online_shadow_enabled")):
        return None
    min_usable_points = max(
        1,
        _to_int(resolved_analysis_config.get("segmented_tail_online_min_usable_points"), 6),
    )
    if segmented_tail_mod is None:
        return {
            "status": "unavailable",
            "fit_status": "unavailable",
            "reason": "segmented_tail_module_unavailable",
            "usable_point_count": 0,
            "min_usable_points": int(min_usable_points),
        }
    source_rows = _segmented_tail_source_rows(scout_summaries, backtrack_summaries)
    trace = segmented_tail_mod.build_tail_width_trace(source_rows)
    if len(trace) < int(min_usable_points):
        return {
            "status": "insufficient_usable_points",
            "fit_status": "insufficient_points",
            "usable_point_count": int(len(trace)),
            "min_usable_points": int(min_usable_points),
            "trace": _copy_jsonish(trace),
            "fit_points": [],
            "tail_start_delay_from_emergence_us": None,
            "tail_start_delta_from_runtime_us": None,
            "runtime_tail_start_delay_from_emergence_us": _to_int(
                runtime_tail_start_delay_from_emergence_us
            ),
            "confidence": "unavailable",
        }
    result = segmented_tail_mod.evaluate_segmented_tail_trace(
        source_rows,
        baseline_width_px=_to_float_or_none(baseline_width_px),
    )
    payload = _compact_segmented_tail_shadow_payload(
        dict(result or {}),
        runtime_tail_start_delay_from_emergence_us=runtime_tail_start_delay_from_emergence_us,
    )
    payload["min_usable_points"] = int(min_usable_points)
    return payload


def resolve_online_stream_tail_result(
    *,
    flow_fit_result: dict | None,
    tail_plan: dict | None,
    scout_summaries: list[dict] | None = None,
    backtrack_summaries: list[dict] | None = None,
    coarse_summaries: list[dict] | None = None,
    refine_summaries: list[dict] | None = None,
    trigger_bracket: dict | None,
    flow_delay_summaries: list[dict] | None = None,
    analysis_config: dict | None = None,
    phase: str = "online_stream_calibration",
    run_segmented_tail_shadow: bool = True,
) -> dict:
    fit = dict(flow_fit_result or {})
    plan = dict(tail_plan or {})
    scout_rows = [
        dict(row or {})
        for row in list(scout_summaries if scout_summaries is not None else coarse_summaries or [])
    ]
    backtrack_rows = [
        dict(row or {})
        for row in list(backtrack_summaries if backtrack_summaries is not None else refine_summaries or [])
    ]
    bracket = dict(trigger_bracket or {})
    resolved_policy = _resolved_policy(plan.get("policy") if isinstance(plan.get("policy"), dict) else None)
    combined_analysis_config = dict(plan.get("analysis_config") or {})
    if isinstance(analysis_config, dict):
        combined_analysis_config.update(dict(analysis_config))
    resolved_analysis_config = _resolved_analysis_config(combined_analysis_config)

    scout_rows = _classify_trace_rows(scout_rows, policy=resolved_policy)
    backtrack_rows = _classify_trace_rows(backtrack_rows, policy=resolved_policy)

    requested_status = str(bracket.get("tail_phase_status") or bracket.get("status") or "").strip()
    termination_reason = str(bracket.get("termination_reason") or "").strip()
    landmark_delay_us = _to_int(bracket.get("landmark_delay_us"), _to_int(bracket.get("trigger_delay_us")))
    landmark_reason = str(bracket.get("landmark_reason") or bracket.get("trigger_reason") or "").strip() or None
    backtrack_left_delay_us = _to_int(
        bracket.get("backtrack_left_delay_us"),
        _to_int(bracket.get("last_nontrigger_delay_us")),
    )
    left_bracket_extended = bool(bracket.get("left_bracket_extended"))

    if landmark_delay_us is None:
        for row in scout_rows:
            if bool(row.get("landmark_detected")):
                landmark_delay_us = _to_int(row.get("delay_us"))
                landmark_reason = str(row.get("landmark_reason") or landmark_reason or "").strip() or None
                break
    landmark_summary = _find_delay_summary(scout_rows, landmark_delay_us)

    if backtrack_left_delay_us is None and landmark_delay_us is not None:
        scout_before_landmark = [
            int(dict(row or {}).get("delay_us"))
            for row in scout_rows
            if _to_int(dict(row or {}).get("delay_us")) is not None
            and _to_int(dict(row or {}).get("delay_us")) < int(landmark_delay_us)
        ]
        if scout_before_landmark:
            backtrack_left_delay_us = max(scout_before_landmark)
        else:
            backtrack_left_delay_us = _to_int(plan.get("scout_anchor_delay_us"))

    baseline_width_px = _to_float_or_none(fit.get("steady_width_baseline_px"))
    left_endpoint_summary = _find_delay_summary(backtrack_rows, backtrack_left_delay_us)
    if left_endpoint_summary is None:
        left_endpoint_summary = _find_delay_summary(scout_rows, backtrack_left_delay_us)
    if left_endpoint_summary is None:
        left_endpoint_summary = _flow_anchor_summary(
            _find_delay_summary(list(flow_delay_summaries or []), backtrack_left_delay_us),
            baseline_width_px,
            phase_label="flow_anchor",
        )

    synthetic_left_bracket_candidate_delay_us = _to_int(plan.get("scout_anchor_delay_us"))
    synthetic_left_bracket_summary = None
    synthetic_left_bracket_row = None
    synthetic_left_bracket_delay_from_emergence_us = None
    synthetic_left_bracket_source = None
    flow_anchor_summary = _find_latest_accepted_flow_summary(
        list(flow_delay_summaries or []),
        max_delay_us=synthetic_left_bracket_candidate_delay_us,
    )
    if flow_anchor_summary is not None:
        synthetic_left_bracket_summary = _flow_anchor_summary(
            flow_anchor_summary,
            baseline_width_px,
            phase_label="flow_anchor",
        )

    local_trace_rows_by_delay = {}
    for row in list(backtrack_rows or []):
        summary = dict(row or {})
        delay_value = _to_int(summary.get("delay_us"))
        if delay_value is None:
            continue
        local_trace_rows_by_delay[int(delay_value)] = summary
    for row in [left_endpoint_summary, landmark_summary]:
        if not row:
            continue
        summary = dict(row or {})
        delay_value = _to_int(summary.get("delay_us"))
        if delay_value is None or int(delay_value) in local_trace_rows_by_delay:
            continue
        local_trace_rows_by_delay[int(delay_value)] = summary
    if synthetic_left_bracket_summary:
        summary = dict(synthetic_left_bracket_summary or {})
        delay_value = _to_int(summary.get("delay_us"))
        if delay_value is not None and int(delay_value) not in local_trace_rows_by_delay:
            local_trace_rows_by_delay[int(delay_value)] = summary
    local_trace = list(local_trace_rows_by_delay.values())
    local_trace = _classify_trace_rows(local_trace, policy=resolved_policy)
    if synthetic_left_bracket_summary:
        synthetic_left_bracket_row = _find_delay_summary(
            local_trace,
            _to_int(synthetic_left_bracket_summary.get("delay_us")),
        )
        if not bool((synthetic_left_bracket_row or {}).get("resolver_plateau_candidate")):
            synthetic_left_bracket_row = None
        else:
            synthetic_left_bracket_delay_from_emergence_us = _to_int(
                synthetic_left_bracket_row.get("delay_from_emergence_us")
            )
            synthetic_left_bracket_source = "last_accepted_flow_anchor"

    landmark_delay_from_emergence_us = _summary_delay_from_emergence(landmark_summary, landmark_delay_us)
    onset_selection_trace = []
    for row in local_trace:
        row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if (
            landmark_delay_from_emergence_us is not None
            and row_delay_from_emergence_us is not None
            and int(row_delay_from_emergence_us) > int(landmark_delay_from_emergence_us)
        ):
            continue
        onset_selection_trace.append(dict(row))

    confirmation_window_us = int(
        resolved_policy.get(
            "resolver_confirmation_window_us",
            DEFAULT_ONLINE_TAIL_POLICY["resolver_confirmation_window_us"],
        )
    )
    confirmed_collapse_row = None
    for index, row in enumerate(onset_selection_trace):
        row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if row_delay_from_emergence_us is None or not bool(row.get("resolver_collapse_candidate")):
            continue
        collapse_confirmed = False
        for later_row in onset_selection_trace[index + 1 :]:
            later_delay_from_emergence_us = _to_int(later_row.get("delay_from_emergence_us"))
            if later_delay_from_emergence_us is None:
                continue
            if int(later_delay_from_emergence_us) <= int(row_delay_from_emergence_us):
                continue
            if int(later_delay_from_emergence_us) > int(row_delay_from_emergence_us) + int(confirmation_window_us):
                break
            if bool(later_row.get("resolver_collapse_candidate")):
                collapse_confirmed = True
                break
        if (
            not collapse_confirmed
            and landmark_delay_from_emergence_us is not None
            and int(landmark_delay_from_emergence_us) > int(row_delay_from_emergence_us)
            and int(landmark_delay_from_emergence_us)
            <= int(row_delay_from_emergence_us) + int(confirmation_window_us)
        ):
            collapse_confirmed = True
        if collapse_confirmed:
            confirmed_collapse_row = dict(row)
            break

    effective_right_bracket_row = (
        dict(confirmed_collapse_row)
        if confirmed_collapse_row is not None
        else (None if landmark_summary is None else dict(landmark_summary))
    )

    last_plateau_row = None
    effective_right_bracket_delay_from_emergence_us = _to_int(
        None if effective_right_bracket_row is None else effective_right_bracket_row.get("delay_from_emergence_us")
    )
    for row in onset_selection_trace:
        row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
        if (
            effective_right_bracket_delay_from_emergence_us is not None
            and row_delay_from_emergence_us is not None
            and int(row_delay_from_emergence_us) >= int(effective_right_bracket_delay_from_emergence_us)
        ):
            break
        if str(row.get("phase") or "") == "flow_anchor":
            continue
        if bool(row.get("resolver_plateau_candidate")):
            last_plateau_row = dict(row)

    transition_rows = []
    if last_plateau_row is not None and effective_right_bracket_row is not None:
        left_delay_from_emergence_us = _to_int(last_plateau_row.get("delay_from_emergence_us"))
        right_delay_from_emergence_us = _to_int(effective_right_bracket_row.get("delay_from_emergence_us"))
        transition_window_start_from_emergence_us = None
        if right_delay_from_emergence_us is not None:
            transition_window_start_from_emergence_us = int(
                int(right_delay_from_emergence_us) - int(confirmation_window_us)
            )
        for row in onset_selection_trace:
            row_delay_from_emergence_us = _to_int(row.get("delay_from_emergence_us"))
            if (
                row_delay_from_emergence_us is None
                or left_delay_from_emergence_us is None
                or right_delay_from_emergence_us is None
            ):
                continue
            if int(row_delay_from_emergence_us) <= int(left_delay_from_emergence_us):
                continue
            if int(row_delay_from_emergence_us) >= int(right_delay_from_emergence_us):
                continue
            if (
                transition_window_start_from_emergence_us is not None
                and int(row_delay_from_emergence_us) < int(transition_window_start_from_emergence_us)
            ):
                continue
            if bool(row.get("resolver_transition_candidate")):
                transition_rows.append(dict(row))

    right_bracket_row = effective_right_bracket_row

    captured_candidate = None
    midpoint_candidate_delay_from_emergence_us = None
    tail_start_selection_method = None
    synthetic_left_bracket_used = False
    if transition_rows and right_bracket_row is not None and last_plateau_row is not None:
        captured_candidate = dict(transition_rows[-1])
        tail_start_selection_method = "latest_transition_before_confirmed_collapse"
    elif right_bracket_row is not None and last_plateau_row is not None:
        left_delay_from_emergence_us = _to_int(last_plateau_row.get("delay_from_emergence_us"))
        right_delay_from_emergence_us = _to_int(right_bracket_row.get("delay_from_emergence_us"))
        if left_delay_from_emergence_us is not None and right_delay_from_emergence_us is not None:
            midpoint_candidate_delay_from_emergence_us = int(
                (int(left_delay_from_emergence_us) + int(right_delay_from_emergence_us)) / 2
            )
            tail_start_selection_method = "plateau_confirmed_collapse_midpoint"
    elif right_bracket_row is not None and synthetic_left_bracket_row is not None:
        right_delay_from_emergence_us = _to_int(right_bracket_row.get("delay_from_emergence_us"))
        if (
            synthetic_left_bracket_delay_from_emergence_us is not None
            and right_delay_from_emergence_us is not None
        ):
            midpoint_candidate_delay_from_emergence_us = int(
                (
                    int(synthetic_left_bracket_delay_from_emergence_us)
                    + int(right_delay_from_emergence_us)
                )
                / 2
            )
            tail_start_selection_method = "flow_anchor_confirmed_collapse_midpoint"
            synthetic_left_bracket_used = True

    initial_confirmed_collapse_delay_from_emergence_us = _to_int(
        None if confirmed_collapse_row is None else confirmed_collapse_row.get("delay_from_emergence_us")
    )
    initial_confirmed_collapse_reason = _confirmed_collapse_reason_for_summary(confirmed_collapse_row)
    initial_collapse_window_us = None
    if (
        last_plateau_row is not None
        and initial_confirmed_collapse_delay_from_emergence_us is not None
        and _to_int(last_plateau_row.get("delay_from_emergence_us")) is not None
    ):
        initial_collapse_window_us = int(
            int(initial_confirmed_collapse_delay_from_emergence_us)
            - int(_to_int(last_plateau_row.get("delay_from_emergence_us")))
        )

    warnings = _unique_strings(
        list(plan.get("warnings") or [])
        + list(bracket.get("warnings") or [])
        + [warning for row in scout_rows for warning in list(row.get("warnings") or [])]
        + [warning for row in backtrack_rows for warning in list(row.get("warnings") or [])]
    )

    late_frame_warning = bool(
        any(bool(row.get("late_frame_warning")) for row in scout_rows)
        or any(bool(row.get("late_frame_warning")) for row in backtrack_rows)
    )

    tail_phase_status = requested_status or ""
    tail_start_delay_from_emergence_us = None
    tail_start_evidence = None
    if tail_phase_status in {
        "unresolved_missing_flow_baseline",
        "unresolved_budget_exhausted",
        "unresolved_qc_failure",
        "unresolved_no_landmark",
        "unresolved_missing_left_bracket",
    }:
        pass
    elif landmark_summary is None:
        tail_phase_status = "unresolved_no_landmark"
        if not termination_reason:
            termination_reason = "no_scout_landmark"
        if "unresolved_no_landmark" not in warnings:
            warnings.append("unresolved_no_landmark")
    elif captured_candidate is not None:
        tail_phase_status = "captured"
        termination_reason = termination_reason or "backtrack_width_departure"
        tail_start_delay_from_emergence_us = _to_int(captured_candidate.get("delay_from_emergence_us"))
        if (
            _to_int(captured_candidate.get("delay_us")) == _to_int(landmark_summary.get("delay_us"))
            and str(landmark_summary.get("landmark_reason") or "") == "strong_width_collapse_backup"
        ):
            tail_start_evidence = "width_collapse_backup"
        else:
            tail_start_evidence = "backtrack_width_departure"
    elif midpoint_candidate_delay_from_emergence_us is not None:
        tail_phase_status = "captured"
        termination_reason = termination_reason or (
            "flow_anchor_right_bracket_midpoint"
            if bool(synthetic_left_bracket_used)
            else "plateau_right_bracket_midpoint"
        )
        tail_start_delay_from_emergence_us = int(midpoint_candidate_delay_from_emergence_us)
        tail_start_evidence = (
            "flow_anchor_right_bracket_midpoint"
            if bool(synthetic_left_bracket_used)
            else "plateau_right_bracket_midpoint"
        )
    elif right_bracket_row is not None:
        tail_phase_status = "unresolved_missing_left_bracket"
        termination_reason = termination_reason or "missing_left_bracket"
        if "unresolved_missing_left_bracket" not in warnings:
            warnings.append("unresolved_missing_left_bracket")
    else:
        tail_phase_status = "unresolved_no_landmark"
        termination_reason = termination_reason or "no_scout_landmark"
        if "unresolved_no_landmark" not in warnings:
            warnings.append("unresolved_no_landmark")

    tail_settling_rule_applied = False
    tail_settling_rule_reason = "disabled"
    tail_settling_diagnostics = {
        "tail_settling_candidate_delay_from_emergence_us": None,
        "tail_settling_trace_window_end_delay_from_emergence_us": None,
        "tail_settling_progress_threshold": float(TAIL_SETTLING_PROGRESS_THRESHOLD),
    }
    if bool(resolved_analysis_config.get("tail_settling_rule_enabled")):
        tail_settling_rule_reason = "selection_method_ineligible"
        if (
            tail_phase_status == "captured"
            and tail_start_delay_from_emergence_us is not None
            and tail_start_selection_method in {
                "earliest_transition_before_confirmed_collapse",
                "latest_transition_before_confirmed_collapse",
            }
            and str(landmark_reason or "") == "separated_from_nozzle"
        ):
            if initial_collapse_window_us is None:
                tail_settling_rule_reason = "missing_collapse_window"
            elif int(initial_collapse_window_us) < int(TAIL_SETTLING_MIN_COLLAPSE_WINDOW_US):
                tail_settling_rule_reason = "collapse_window_too_short"
            else:
                tail_settling_diagnostics = _tail_settling_candidate(
                    local_trace=local_trace,
                    last_plateau_row=last_plateau_row,
                    initial_confirmed_collapse_delay_from_emergence_us=initial_confirmed_collapse_delay_from_emergence_us,
                )
                candidate_delay_from_emergence_us = _to_int(
                    tail_settling_diagnostics.get("tail_settling_candidate_delay_from_emergence_us")
                )
                if candidate_delay_from_emergence_us is None:
                    tail_settling_rule_reason = str(
                        tail_settling_diagnostics.get("tail_settling_candidate_reason")
                        or "missing_candidate"
                    )
                elif int(candidate_delay_from_emergence_us) < int(tail_start_delay_from_emergence_us) + int(
                    TAIL_SETTLING_MIN_DELAY_SHIFT_US
                ):
                    tail_settling_rule_reason = "candidate_shift_below_min"
                else:
                    tail_settling_rule_applied = True
                    tail_settling_rule_reason = "applied"
                    tail_start_delay_from_emergence_us = int(candidate_delay_from_emergence_us)
                    tail_start_selection_method = TAIL_SETTLING_SELECTION_METHOD
                    tail_start_evidence = "tail_settling_progress90"
                    if confirmed_collapse_row is None:
                        confirmed_collapse_row = {}
                    confirmed_collapse_row = {
                        **dict(confirmed_collapse_row or {}),
                        "delay_from_emergence_us": int(candidate_delay_from_emergence_us),
                    }
    else:
        tail_settling_rule_reason = "disabled"

    predicted_stream_duration_us = None
    predicted_volume_nl = None
    flow_rate = _to_float_or_none(fit.get("flow_rate_nl_per_us"))
    flow_intercept = _to_float_or_none(fit.get("flow_intercept_nl"))
    if (
        tail_phase_status == "captured"
        and tail_start_delay_from_emergence_us is not None
        and flow_rate is not None
        and flow_intercept is not None
    ):
        predicted_stream_duration_us = int(tail_start_delay_from_emergence_us)
        predicted_volume_nl = float(
            float(flow_intercept) + (float(flow_rate) * float(predicted_stream_duration_us))
        )

    landmark_delay_from_emergence_us = _summary_delay_from_emergence(landmark_summary, landmark_delay_us)
    fine_window_delays_us = build_online_stream_tail_backtrack_plan(
        scout_anchor_delay_us=_to_int(plan.get("scout_anchor_delay_us")),
        left_endpoint_delay_us=backtrack_left_delay_us,
        landmark_delay_us=landmark_delay_us,
        backtrack_step_us=int(plan.get("backtrack_step_us") or DEFAULT_ONLINE_TAIL_POLICY["backtrack_step_us"]),
        fine_prepad_us=_to_int(plan.get("fine_prepad_us"), DEFAULT_ONLINE_TAIL_POLICY["fine_prepad_us"]),
        fine_postpad_us=_to_int(plan.get("fine_postpad_us"), DEFAULT_ONLINE_TAIL_POLICY["fine_postpad_us"]),
    )
    if backtrack_rows:
        sampled_backtrack_delays_us = sorted(
            int(dict(row or {}).get("delay_us"))
            for row in backtrack_rows
            if _to_int(dict(row or {}).get("delay_us")) is not None
        )
        if sampled_backtrack_delays_us:
            fine_window_delays_us = list(sampled_backtrack_delays_us)
    fine_window_start_delay_us = fine_window_delays_us[0] if fine_window_delays_us else backtrack_left_delay_us
    fine_window_end_delay_us = fine_window_delays_us[-1] if fine_window_delays_us else landmark_delay_us
    backtrack_window_start_delay_from_emergence_us = _delay_from_emergence_from_plan(
        plan,
        fine_window_start_delay_us,
    )
    if backtrack_window_start_delay_from_emergence_us is None:
        backtrack_window_start_delay_from_emergence_us = _summary_delay_from_emergence(
            left_endpoint_summary,
            fine_window_start_delay_us,
        )
    backtrack_window_end_delay_from_emergence_us = _delay_from_emergence_from_plan(
        plan,
        fine_window_end_delay_us,
    )
    if backtrack_window_end_delay_from_emergence_us is None:
        backtrack_window_end_delay_from_emergence_us = _summary_delay_from_emergence(
            landmark_summary,
            fine_window_end_delay_us,
        )

    all_summaries = list(scout_rows) + list(backtrack_rows)
    right_bracket_delay_from_emergence_us = _to_int(
        None if right_bracket_row is None else right_bracket_row.get("delay_from_emergence_us")
    )
    right_bracket_reason = _right_bracket_reason_for_summary(right_bracket_row)
    confirmed_collapse_delay_from_emergence_us = _to_int(
        None if confirmed_collapse_row is None else confirmed_collapse_row.get("delay_from_emergence_us")
    )
    confirmed_collapse_reason = (
        TAIL_SETTLING_SELECTION_METHOD
        if bool(tail_settling_rule_applied)
        else _confirmed_collapse_reason_for_summary(confirmed_collapse_row)
    )
    last_plateau_delay_from_emergence_us = _to_int(
        None if last_plateau_row is None else last_plateau_row.get("delay_from_emergence_us")
    )
    right_edge_coverage = _tail_right_edge_coverage_summary(
        backtrack_rows,
        policy=resolved_policy,
    )
    segmented_tail_shadow = None
    if bool(run_segmented_tail_shadow):
        segmented_tail_shadow = evaluate_online_stream_segmented_tail_shadow(
            scout_summaries=scout_rows,
            backtrack_summaries=backtrack_rows,
            baseline_width_px=(
                baseline_width_px
                if baseline_width_px is not None
                else _to_float_or_none(plan.get("steady_width_baseline_px"))
            ),
            runtime_tail_start_delay_from_emergence_us=tail_start_delay_from_emergence_us,
            analysis_config=resolved_analysis_config,
        )
    segmented_predicted_stream_duration_us = None
    segmented_predicted_volume_nl = None
    segmented_predicted_volume_delta_from_runtime_nl = None
    if isinstance(segmented_tail_shadow, dict):
        segmented_tail_shadow = dict(segmented_tail_shadow)
        segmented_tail_start_delay_from_emergence_us = _to_int(
            segmented_tail_shadow.get("tail_start_delay_from_emergence_us")
        )
        if (
            segmented_tail_start_delay_from_emergence_us is not None
            and flow_rate is not None
            and flow_intercept is not None
        ):
            segmented_predicted_stream_duration_us = int(
                segmented_tail_start_delay_from_emergence_us
            )
            segmented_predicted_volume_nl = float(
                float(flow_intercept)
                + (float(flow_rate) * float(segmented_predicted_stream_duration_us))
            )
        if segmented_predicted_volume_nl is not None and predicted_volume_nl is not None:
            segmented_predicted_volume_delta_from_runtime_nl = float(
                float(segmented_predicted_volume_nl) - float(predicted_volume_nl)
            )
        segmented_tail_shadow["predicted_stream_duration_us"] = (
            None
            if segmented_predicted_stream_duration_us is None
            else int(segmented_predicted_stream_duration_us)
        )
        segmented_tail_shadow["predicted_volume_nl"] = (
            None if segmented_predicted_volume_nl is None else float(segmented_predicted_volume_nl)
        )
        segmented_tail_shadow["runtime_predicted_volume_nl"] = (
            None if predicted_volume_nl is None else float(predicted_volume_nl)
        )
        segmented_tail_shadow["predicted_volume_delta_from_runtime_nl"] = (
            None
            if segmented_predicted_volume_delta_from_runtime_nl is None
            else float(segmented_predicted_volume_delta_from_runtime_nl)
        )
    tail_phase = {
        "status": str(tail_phase_status or "unresolved_no_landmark"),
        "plan": _copy_jsonish(plan),
        "analysis_config": _copy_jsonish(resolved_analysis_config),
        "search_method": SEARCH_METHOD,
        "max_scout_delay_count": _to_int(plan.get("max_scout_delay_count")),
        "fine_prepad_us": _to_int(plan.get("fine_prepad_us")),
        "fine_postpad_us": _to_int(plan.get("fine_postpad_us")),
        "reserved_backtrack_capture_count": _to_int(plan.get("reserved_backtrack_capture_count")),
        "required_tail_capture_count": _to_int(plan.get("required_tail_capture_count")),
        "required_tail_scout_capture_count": _to_int(plan.get("required_tail_scout_capture_count")),
        "required_tail_backtrack_capture_count": _to_int(
            plan.get("required_tail_backtrack_capture_count")
        ),
        "required_tail_left_extension_capture_count": _to_int(
            plan.get("required_tail_left_extension_capture_count")
        ),
        "attempted_delay_count": int(len(all_summaries)),
        "attempted_capture_count": int(
            sum(max(0, _to_int(row.get("attempted_replicates"), 0)) for row in all_summaries)
        ),
        "accepted_delay_count": int(sum(1 for row in all_summaries if bool(row.get("delay_accepted")))),
        "accepted_measurement_count": int(
            sum(max(0, _to_int(row.get("accepted_replicates"), 0)) for row in all_summaries)
        ),
        "termination_reason": str(termination_reason),
        "scout_delay_summaries": _copy_jsonish(scout_rows),
        "backtrack_delay_summaries": _copy_jsonish(backtrack_rows),
        "coarse_delay_summaries": _copy_jsonish(scout_rows),
        "refine_delay_summaries": _copy_jsonish(backtrack_rows),
        "landmark_delay_from_emergence_us": landmark_delay_from_emergence_us,
        "landmark_reason": landmark_reason or (None if landmark_summary is None else landmark_summary.get("landmark_reason")),
        "initial_confirmed_collapse_delay_from_emergence_us": initial_confirmed_collapse_delay_from_emergence_us,
        "initial_confirmed_collapse_reason": initial_confirmed_collapse_reason,
        "confirmed_collapse_delay_from_emergence_us": confirmed_collapse_delay_from_emergence_us,
        "confirmed_collapse_reason": confirmed_collapse_reason,
        "right_bracket_delay_from_emergence_us": right_bracket_delay_from_emergence_us,
        "right_bracket_reason": right_bracket_reason,
        "last_plateau_delay_from_emergence_us": last_plateau_delay_from_emergence_us,
        "initial_collapse_window_us": initial_collapse_window_us,
        "left_bracket_extended": bool(left_bracket_extended),
        "left_bracket_confirmed": bool(last_plateau_row is not None),
        "tail_backtrack_compressed": bool(plan.get("tail_backtrack_compressed")),
        "tail_backtrack_requested_capture_count": _to_int(
            plan.get("tail_backtrack_requested_capture_count")
        ),
        "tail_backtrack_applied_capture_count": _to_int(
            plan.get("tail_backtrack_applied_capture_count")
        ),
        "backtrack_window_start_delay_from_emergence_us": backtrack_window_start_delay_from_emergence_us,
        "backtrack_window_end_delay_from_emergence_us": backtrack_window_end_delay_from_emergence_us,
        "fine_window_start_delay_from_emergence_us": backtrack_window_start_delay_from_emergence_us,
        "fine_window_end_delay_from_emergence_us": backtrack_window_end_delay_from_emergence_us,
        "tail_start_evidence": tail_start_evidence,
        "tail_start_selection_method": tail_start_selection_method,
        "tail_settling_rule_applied": bool(tail_settling_rule_applied),
        "tail_settling_rule_reason": str(tail_settling_rule_reason),
        "tail_settling_candidate_delay_from_emergence_us": _to_int(
            tail_settling_diagnostics.get("tail_settling_candidate_delay_from_emergence_us")
        ),
        "tail_settling_trace_window_end_delay_from_emergence_us": _to_int(
            tail_settling_diagnostics.get("tail_settling_trace_window_end_delay_from_emergence_us")
        ),
        "tail_settling_progress_threshold": _to_float_or_none(
            tail_settling_diagnostics.get("tail_settling_progress_threshold")
        ),
        "tail_backup_landmark_confirmed": bool(bracket.get("tail_backup_landmark_confirmed")),
        "tail_backup_landmark_confirmation_reason": (
            str(bracket.get("tail_backup_landmark_confirmation_reason") or "") or None
        ),
        "tail_collapse_coverage_ok": bool(right_edge_coverage.get("tail_collapse_coverage_ok")),
        "tail_right_extension_needed": bool(right_edge_coverage.get("tail_right_extension_needed")),
        "tail_right_extension_reason": right_edge_coverage.get("tail_right_extension_reason"),
        "tail_right_extension_count": _to_int(plan.get("tail_right_extension_count"), 0),
        "tail_min_width_delay_from_emergence_us": _to_int(
            right_edge_coverage.get("tail_min_width_delay_from_emergence_us")
        ),
        "tail_min_width_at_right_edge": bool(right_edge_coverage.get("tail_min_width_at_right_edge")),
        "tail_width_still_falling_at_right_edge": bool(
            right_edge_coverage.get("tail_width_still_falling_at_right_edge")
        ),
        "tail_selection_noise_floor_px": _to_float_or_none(
            right_edge_coverage.get("tail_selection_noise_floor_px")
        ),
        "trigger_delay_from_emergence_us": landmark_delay_from_emergence_us,
        "trigger_reason": landmark_reason or (None if landmark_summary is None else landmark_summary.get("landmark_reason")),
        "last_nontrigger_delay_from_emergence_us": (
            synthetic_left_bracket_delay_from_emergence_us
            if bool(synthetic_left_bracket_used)
            else last_plateau_delay_from_emergence_us
        ),
        "synthetic_left_bracket_used": bool(synthetic_left_bracket_used),
        "synthetic_left_bracket_delay_from_emergence_us": (
            _to_int(synthetic_left_bracket_delay_from_emergence_us)
            if bool(synthetic_left_bracket_used)
            else None
        ),
        "synthetic_left_bracket_source": (
            str(synthetic_left_bracket_source)
            if bool(synthetic_left_bracket_used) and synthetic_left_bracket_source is not None
            else None
        ),
        "late_frame_warning": bool(late_frame_warning),
        "tail_retarget_count": _to_int(plan.get("tail_retarget_count"), 0),
        "retargeted_coarse_start_delay_us": _to_int(plan.get("retargeted_coarse_start_delay_us")),
        "tail_start_delay_from_emergence_us": (
            None if tail_start_delay_from_emergence_us is None else int(tail_start_delay_from_emergence_us)
        ),
        "warnings": _copy_warnings(warnings),
    }
    if segmented_tail_shadow is not None:
        tail_phase["segmented_tail"] = _copy_jsonish(segmented_tail_shadow)
        tail_phase["segmented_tail_start_delay_from_emergence_us"] = _to_int(
            segmented_tail_shadow.get("tail_start_delay_from_emergence_us")
        )
        tail_phase["segmented_tail_start_delta_from_runtime_us"] = _to_int(
            segmented_tail_shadow.get("tail_start_delta_from_runtime_us")
        )
        tail_phase["segmented_predicted_stream_duration_us"] = (
            None
            if segmented_predicted_stream_duration_us is None
            else int(segmented_predicted_stream_duration_us)
        )
        tail_phase["segmented_predicted_volume_nl"] = (
            None if segmented_predicted_volume_nl is None else float(segmented_predicted_volume_nl)
        )
        tail_phase["segmented_predicted_volume_delta_from_runtime_nl"] = (
            None
            if segmented_predicted_volume_delta_from_runtime_nl is None
            else float(segmented_predicted_volume_delta_from_runtime_nl)
        )
    return {
        "phase": str(phase),
        "tail_phase": tail_phase,
        "predicted_stream_duration_us": (
            None if predicted_stream_duration_us is None else int(predicted_stream_duration_us)
        ),
        "predicted_volume_nl": None if predicted_volume_nl is None else float(predicted_volume_nl),
        "warnings": _copy_warnings(warnings),
    }


def build_online_stream_tail_fit_artifact(
    *,
    condition: dict | None = None,
    tail_plan: dict | None = None,
    steady_width_baseline_px: float | int | None = None,
    scout_delay_summaries: list[dict] | None = None,
    backtrack_delay_summaries: list[dict] | None = None,
    coarse_delay_summaries: list[dict] | None = None,
    refine_delay_summaries: list[dict] | None = None,
    result: dict | None = None,
    warnings: list[str] | None = None,
    schema_version: int = 1,
    phase: str = "online_stream_calibration",
) -> dict:
    result_obj = dict(result or {})
    resolved_scout_rows = scout_delay_summaries if scout_delay_summaries is not None else coarse_delay_summaries or []
    resolved_backtrack_rows = (
        backtrack_delay_summaries if backtrack_delay_summaries is not None else refine_delay_summaries or []
    )
    return {
        "schema_version": int(schema_version),
        "phase": str(phase),
        "condition": _copy_jsonish(condition or {}),
        "tail_plan": _copy_jsonish(tail_plan or {}),
        "steady_width_baseline_px": _to_float_or_none(
            steady_width_baseline_px
            if steady_width_baseline_px is not None
            else (tail_plan or {}).get("steady_width_baseline_px")
        ),
        "search_method": SEARCH_METHOD,
        "scout_delay_summaries": _copy_jsonish(resolved_scout_rows),
        "backtrack_delay_summaries": _copy_jsonish(resolved_backtrack_rows),
        "coarse_delay_summaries": _copy_jsonish(resolved_scout_rows),
        "refine_delay_summaries": _copy_jsonish(resolved_backtrack_rows),
        "result": _copy_jsonish(result_obj),
        "warnings": _copy_warnings(
            warnings if warnings is not None else result_obj.get("warnings")
        ),
    }
