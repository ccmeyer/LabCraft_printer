from __future__ import annotations

import math
import statistics
from collections import defaultdict

import numpy as np


MODEL_PLATEAU = "plateau"
MODEL_PLATEAU_DECLINE = "plateau_decline"
MODEL_PLATEAU_SHOULDER_COLLAPSE = "plateau_shoulder_collapse"
MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE = (
    "plateau_gradual_shoulder_steep_shoulder_collapse"
)
MODEL_THREE_BREAK_TWO_BREAK_MIDPOINT = "three_break_two_break_midpoint"
TAIL_START_SOURCE_REFERENCE_MODEL = "reference_model"
TAIL_START_SOURCE_THREE_BREAK_TAU1 = "three_break_tau1"
TAIL_START_SOURCE_THREE_TWO_MIDPOINT = "three_two_midpoint"

MIN_NOISE_FLOOR_PX = 0.75
MIN_SEGMENT_POINTS = 2
MIN_BREAK_GAP_US = 100
BREAKPOINT_REFINEMENT_STEP_US = 25
BIC_IMPROVEMENT_THRESHOLD = 2.0
THREE_BREAK_MAX_TAIL_START_ADVANCE_US = 200
THREE_BREAK_MIN_EARLY_SHOULDER_SLOPE_PX_PER_MS = 10.0
THREE_BREAK_LOCAL_CONFIRMATION_MIN_DROP_PX = 1.5
THREE_BREAK_LOCAL_CONFIRMATION_MAX_REBOUND_PX = 0.5
THREE_BREAK_LOCAL_CONFIRMATION_FUTURE_POINTS = 2


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return parsed
    except Exception:
        return None


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _median(values):
    clean = [float(value) for value in values if _float_or_none(value) is not None]
    if not clean:
        return None
    return float(statistics.median(clean))


def _mad(values):
    clean = [float(value) for value in values if _float_or_none(value) is not None]
    if len(clean) < 2:
        return None
    center = statistics.median(clean)
    deviations = [abs(value - center) for value in clean]
    return float(statistics.median(deviations))


def build_tail_width_trace(tail_rows: list[dict] | None) -> list[dict]:
    """Median-aggregate usable tail width rows by delay from emergence."""

    grouped: dict[int, list[float]] = defaultdict(list)
    phases: dict[int, set[str]] = defaultdict(set)
    for row in list(tail_rows or []):
        item = dict(row or {})
        if not bool(item.get("tail_width_usable")):
            continue
        delay = _int_or_none(item.get("delay_from_emergence_us"))
        width = _float_or_none(item.get("attached_width_px"))
        if delay is None or width is None:
            continue
        grouped[int(delay)].append(float(width))
        phase = str(item.get("phase") or "").strip()
        if phase:
            phases[int(delay)].add(phase)

    trace = []
    for delay in sorted(grouped):
        widths = grouped[delay]
        median_width = _median(widths)
        if median_width is None:
            continue
        trace.append(
            {
                "delay_from_emergence_us": int(delay),
                "median_width_px": float(median_width),
                "sample_count": int(len(widths)),
                "phases": sorted(phases.get(delay) or []),
            }
        )
    return trace


def _estimate_noise_px(widths: np.ndarray, *, baseline_width_px: float | None) -> float:
    values = [float(value) for value in np.asarray(widths, dtype=float).tolist()]
    candidates = []
    if baseline_width_px is not None and math.isfinite(float(baseline_width_px)):
        tolerance = max(1.5, 0.03 * abs(float(baseline_width_px)))
        candidates = [value for value in values if abs(value - float(baseline_width_px)) <= tolerance]
    if len(candidates) < 3:
        candidates = values[: min(len(values), 5)]
    mad = _mad(candidates)
    if mad is None:
        return float(MIN_NOISE_FLOOR_PX)
    robust_sigma = float(1.4826 * float(mad))
    if not math.isfinite(robust_sigma):
        robust_sigma = 0.0
    return float(max(MIN_NOISE_FLOOR_PX, robust_sigma))


def _bic(sse: float, n: int, k: int, *, noise_floor: float) -> float:
    safe_n = max(1, int(n))
    safe_sse = max(float(sse), (float(noise_floor) ** 2) * 1.0e-6)
    return float(safe_n * math.log(safe_sse / safe_n) + int(k) * math.log(safe_n))


def _plateau_fit(y: np.ndarray, *, noise_floor: float) -> dict:
    c = float(np.median(y))
    fitted = np.full_like(y, c, dtype=float)
    residuals = y - fitted
    sse = float(np.sum(residuals * residuals))
    return {
        "model_name": MODEL_PLATEAU,
        "bic": _bic(sse, len(y), 1, noise_floor=noise_floor),
        "sse": sse,
        "params": {"width_px": c},
        "fitted_widths_px": fitted.tolist(),
        "tail_start_delay_from_emergence_us": None,
        "knee_delay_from_emergence_us": None,
        "second_knee_delay_from_emergence_us": None,
        "breakpoint_delays_from_emergence_us": [],
    }


def _least_squares():
    from scipy.optimize import least_squares

    return least_squares


def _as_int_delay(value):
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return int(round(float(parsed)))


def _observed_delay_set(delays_us: np.ndarray) -> set[int]:
    return {
        int(round(float(value)))
        for value in np.asarray(delays_us, dtype=float).tolist()
    }


def _breakpoint_observed_flags(delays_us: np.ndarray, breakpoints_us: list) -> list[bool]:
    observed = _observed_delay_set(delays_us)
    return [
        _as_int_delay(value) in observed
        for value in list(breakpoints_us or [])
        if _as_int_delay(value) is not None
    ]


def _tail_start_observed_delay(delays_us: np.ndarray, tail_start_us) -> bool | None:
    tail_start = _as_int_delay(tail_start_us)
    if tail_start is None:
        return None
    return bool(tail_start in _observed_delay_set(delays_us))


def _round_to_step_us(value, step_us: int) -> int | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    step = max(1, int(step_us))
    return int(math.floor((float(parsed) / float(step)) + 0.5) * step)


def _refinement_values(
    tau_us,
    delays_us: np.ndarray,
    *,
    breakpoint_refinement_step_us: int,
) -> list[float]:
    tau = _float_or_none(tau_us)
    if tau is None:
        return []
    step = int(breakpoint_refinement_step_us)
    if step <= 0:
        return [float(tau)]
    min_delay = float(np.min(delays_us))
    max_delay = float(np.max(delays_us))
    values = []
    for candidate in [float(tau) - float(step), float(tau), float(tau) + float(step)]:
        clipped = min(max(float(candidate), min_delay), max_delay)
        if all(abs(float(clipped) - float(existing)) > 1.0e-6 for existing in values):
            values.append(float(clipped))
    return sorted(values)


def _count_le(delays_us: np.ndarray, tau_us: float) -> int:
    return int(np.count_nonzero(np.asarray(delays_us, dtype=float) <= float(tau_us)))


def _count_ge(delays_us: np.ndarray, tau_us: float) -> int:
    return int(np.count_nonzero(np.asarray(delays_us, dtype=float) >= float(tau_us)))


def _count_between_inclusive(delays_us: np.ndarray, start_us: float, end_us: float) -> int:
    delays = np.asarray(delays_us, dtype=float)
    return int(np.count_nonzero((delays >= float(start_us)) & (delays <= float(end_us))))


def _one_break_prediction(x_ms: np.ndarray, tau_ms: float, params: np.ndarray) -> np.ndarray:
    c, slope = params
    return c + slope * np.maximum(0.0, x_ms - float(tau_ms))


def _two_break_prediction(
    x_ms: np.ndarray,
    tau1_ms: float,
    tau2_ms: float,
    params: np.ndarray,
) -> np.ndarray:
    c, shoulder_slope, collapse_delta_slope = params
    return (
        c
        + shoulder_slope * np.maximum(0.0, x_ms - float(tau1_ms))
        + collapse_delta_slope * np.maximum(0.0, x_ms - float(tau2_ms))
    )


def _three_break_prediction(
    x_ms: np.ndarray,
    tau1_ms: float,
    tau2_ms: float,
    tau3_ms: float,
    params: np.ndarray,
) -> np.ndarray:
    c, shoulder_slope, steep_shoulder_delta_slope, collapse_delta_slope = params
    return (
        c
        + shoulder_slope * np.maximum(0.0, x_ms - float(tau1_ms))
        + steep_shoulder_delta_slope * np.maximum(0.0, x_ms - float(tau2_ms))
        + collapse_delta_slope * np.maximum(0.0, x_ms - float(tau3_ms))
    )


def _fit_one_break_candidate(
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    tau_us: float,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
) -> dict | None:
    if len(y) < int(min_segment_points) * 2:
        return None
    tau_us = float(tau_us)
    left_count = _count_le(delays_us, tau_us)
    right_count = _count_ge(delays_us, tau_us)
    if left_count < int(min_segment_points) or right_count < int(min_segment_points):
        return None
    if int(float(delays_us[-1]) - tau_us) < int(min_break_gap_us):
        return None
    least_squares = _least_squares()
    tau_ms = float((tau_us - float(delays_us[0])) / 1000.0)
    left_widths = y[np.asarray(delays_us, dtype=float) <= tau_us]
    left_width = float(np.median(left_widths))
    slope_guess = min(0.0, float((y[-1] - left_width) / max(1.0e-6, x_ms[-1] - tau_ms)))
    result = least_squares(
        lambda params: y - _one_break_prediction(x_ms, tau_ms, params),
        x0=np.asarray([left_width, slope_guess], dtype=float),
        bounds=([-np.inf, -np.inf], [np.inf, 0.0]),
        loss="soft_l1",
        f_scale=float(noise_floor),
        max_nfev=200,
    )
    fitted = _one_break_prediction(x_ms, tau_ms, result.x)
    residuals = y - fitted
    sse = float(np.sum(residuals * residuals))
    tau_delay = int(round(float(tau_us)))
    return {
        "model_name": MODEL_PLATEAU_DECLINE,
        "bic": _bic(sse, len(y), 3, noise_floor=noise_floor),
        "sse": sse,
        "params": {
            "width_px": float(result.x[0]),
            "decline_slope_px_per_ms": float(result.x[1]),
        },
        "fitted_widths_px": fitted.tolist(),
        "tail_start_delay_from_emergence_us": tau_delay,
        "knee_delay_from_emergence_us": None,
        "second_knee_delay_from_emergence_us": None,
        "breakpoint_delays_from_emergence_us": [tau_delay],
        "breakpoint_observed_delays": _breakpoint_observed_flags(delays_us, [tau_delay]),
        "tail_start_observed_delay": _tail_start_observed_delay(delays_us, tau_delay),
    }


def _refine_one_break(
    best: dict | None,
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
    breakpoint_refinement_step_us: int,
) -> dict | None:
    if best is None or int(breakpoint_refinement_step_us) <= 0:
        return best
    refined = best
    for tau_us in _refinement_values(
        best.get("tail_start_delay_from_emergence_us"),
        delays_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    ):
        candidate = _fit_one_break_candidate(
            delays_us,
            x_ms,
            y,
            tau_us=float(tau_us),
            noise_floor=noise_floor,
            min_segment_points=min_segment_points,
            min_break_gap_us=min_break_gap_us,
        )
        if candidate is not None and float(candidate["bic"]) < float(refined["bic"]):
            refined = candidate
    return refined


def _fit_one_break(
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
    breakpoint_refinement_step_us: int,
) -> dict | None:
    if len(y) < int(min_segment_points) * 2:
        return None
    best = None
    for tau_us in delays_us.tolist():
        candidate = _fit_one_break_candidate(
            delays_us,
            x_ms,
            y,
            tau_us=float(tau_us),
            noise_floor=noise_floor,
            min_segment_points=min_segment_points,
            min_break_gap_us=min_break_gap_us,
        )
        if candidate is not None and (best is None or float(candidate["bic"]) < float(best["bic"])):
            best = candidate
    return _refine_one_break(
        best,
        delays_us,
        x_ms,
        y,
        noise_floor=noise_floor,
        min_segment_points=min_segment_points,
        min_break_gap_us=min_break_gap_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )


def _fit_two_break_candidate(
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    tau1_us: float,
    tau2_us: float,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
) -> dict | None:
    if len(y) < max(6, int(min_segment_points) * 3):
        return None
    tau1_us = float(tau1_us)
    tau2_us = float(tau2_us)
    if tau2_us <= tau1_us:
        return None
    if int(tau2_us - tau1_us) < int(min_break_gap_us):
        return None
    if _count_le(delays_us, tau1_us) < int(min_segment_points):
        return None
    if _count_between_inclusive(delays_us, tau1_us, tau2_us) < int(min_segment_points):
        return None
    if _count_ge(delays_us, tau2_us) < int(min_segment_points):
        return None
    least_squares = _least_squares()
    tau1_ms = float((tau1_us - float(delays_us[0])) / 1000.0)
    tau2_ms = float((tau2_us - float(delays_us[0])) / 1000.0)
    left_widths = y[np.asarray(delays_us, dtype=float) <= tau1_us]
    left_width = float(np.median(left_widths))
    y_tau2 = float(np.interp(tau2_us, delays_us, y))
    shoulder_guess = min(
        0.0,
        float((y_tau2 - left_width) / max(1.0e-6, tau2_ms - tau1_ms)),
    )
    total_slope_guess = min(
        shoulder_guess,
        float((y[-1] - y_tau2) / max(1.0e-6, x_ms[-1] - tau2_ms)),
    )
    delta_guess = min(0.0, total_slope_guess - shoulder_guess)
    result = least_squares(
        lambda params: y - _two_break_prediction(x_ms, tau1_ms, tau2_ms, params),
        x0=np.asarray([left_width, shoulder_guess, delta_guess], dtype=float),
        bounds=([-np.inf, -np.inf, -np.inf], [np.inf, 0.0, 0.0]),
        loss="soft_l1",
        f_scale=float(noise_floor),
        max_nfev=300,
    )
    fitted = _two_break_prediction(x_ms, tau1_ms, tau2_ms, result.x)
    residuals = y - fitted
    sse = float(np.sum(residuals * residuals))
    tau1_delay = int(round(float(tau1_us)))
    tau2_delay = int(round(float(tau2_us)))
    breakpoints = [tau1_delay, tau2_delay]
    return {
        "model_name": MODEL_PLATEAU_SHOULDER_COLLAPSE,
        "bic": _bic(sse, len(y), 5, noise_floor=noise_floor),
        "sse": sse,
        "params": {
            "width_px": float(result.x[0]),
            "shoulder_slope_px_per_ms": float(result.x[1]),
            "collapse_delta_slope_px_per_ms": float(result.x[2]),
            "collapse_slope_px_per_ms": float(result.x[1] + result.x[2]),
        },
        "fitted_widths_px": fitted.tolist(),
        "tail_start_delay_from_emergence_us": tau1_delay,
        "knee_delay_from_emergence_us": tau2_delay,
        "second_knee_delay_from_emergence_us": None,
        "breakpoint_delays_from_emergence_us": breakpoints,
        "breakpoint_observed_delays": _breakpoint_observed_flags(delays_us, breakpoints),
        "tail_start_observed_delay": _tail_start_observed_delay(delays_us, tau1_delay),
    }


def _refine_two_break(
    best: dict | None,
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
    breakpoint_refinement_step_us: int,
) -> dict | None:
    if best is None or int(breakpoint_refinement_step_us) <= 0:
        return best
    refined = best
    tau1_values = _refinement_values(
        best.get("tail_start_delay_from_emergence_us"),
        delays_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )
    tau2_values = _refinement_values(
        best.get("knee_delay_from_emergence_us"),
        delays_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )
    for tau1_us in tau1_values:
        for tau2_us in tau2_values:
            candidate = _fit_two_break_candidate(
                delays_us,
                x_ms,
                y,
                tau1_us=float(tau1_us),
                tau2_us=float(tau2_us),
                noise_floor=noise_floor,
                min_segment_points=min_segment_points,
                min_break_gap_us=min_break_gap_us,
            )
            if candidate is not None and float(candidate["bic"]) < float(refined["bic"]):
                refined = candidate
    return refined


def _fit_two_break(
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
    breakpoint_refinement_step_us: int,
) -> dict | None:
    if len(y) < max(6, int(min_segment_points) * 3):
        return None
    best = None
    for tau1_us in delays_us.tolist():
        for tau2_us in delays_us.tolist():
            candidate = _fit_two_break_candidate(
                delays_us,
                x_ms,
                y,
                tau1_us=float(tau1_us),
                tau2_us=float(tau2_us),
                noise_floor=noise_floor,
                min_segment_points=min_segment_points,
                min_break_gap_us=min_break_gap_us,
            )
            if candidate is not None and (best is None or float(candidate["bic"]) < float(best["bic"])):
                best = candidate
    return _refine_two_break(
        best,
        delays_us,
        x_ms,
        y,
        noise_floor=noise_floor,
        min_segment_points=min_segment_points,
        min_break_gap_us=min_break_gap_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )


def _fit_three_break_candidate(
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    tau1_us: float,
    tau2_us: float,
    tau3_us: float,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
) -> dict | None:
    if len(y) < max(8, int(min_segment_points) * 4):
        return None
    tau1_us = float(tau1_us)
    tau2_us = float(tau2_us)
    tau3_us = float(tau3_us)
    if tau2_us <= tau1_us or tau3_us <= tau2_us:
        return None
    if int(tau2_us - tau1_us) < int(min_break_gap_us):
        return None
    if int(tau3_us - tau2_us) < int(min_break_gap_us):
        return None
    if _count_le(delays_us, tau1_us) < int(min_segment_points):
        return None
    if _count_between_inclusive(delays_us, tau1_us, tau2_us) < int(min_segment_points):
        return None
    if _count_between_inclusive(delays_us, tau2_us, tau3_us) < int(min_segment_points):
        return None
    if _count_ge(delays_us, tau3_us) < int(min_segment_points):
        return None
    least_squares = _least_squares()
    tau1_ms = float((tau1_us - float(delays_us[0])) / 1000.0)
    tau2_ms = float((tau2_us - float(delays_us[0])) / 1000.0)
    tau3_ms = float((tau3_us - float(delays_us[0])) / 1000.0)
    left_widths = y[np.asarray(delays_us, dtype=float) <= tau1_us]
    left_width = float(np.median(left_widths))
    y_tau2 = float(np.interp(tau2_us, delays_us, y))
    y_tau3 = float(np.interp(tau3_us, delays_us, y))
    shoulder_guess = min(
        0.0,
        float((y_tau2 - left_width) / max(1.0e-6, tau2_ms - tau1_ms)),
    )
    steep_shoulder_slope_guess = min(
        shoulder_guess,
        float((y_tau3 - y_tau2) / max(1.0e-6, tau3_ms - tau2_ms)),
    )
    collapse_slope_guess = min(
        steep_shoulder_slope_guess,
        float((y[-1] - y_tau3) / max(1.0e-6, x_ms[-1] - tau3_ms)),
    )
    steep_delta_guess = min(0.0, steep_shoulder_slope_guess - shoulder_guess)
    collapse_delta_guess = min(0.0, collapse_slope_guess - steep_shoulder_slope_guess)
    result = least_squares(
        lambda params: y - _three_break_prediction(
            x_ms,
            tau1_ms,
            tau2_ms,
            tau3_ms,
            params,
        ),
        x0=np.asarray(
            [left_width, shoulder_guess, steep_delta_guess, collapse_delta_guess],
            dtype=float,
        ),
        bounds=([-np.inf, -np.inf, -np.inf, -np.inf], [np.inf, 0.0, 0.0, 0.0]),
        loss="soft_l1",
        f_scale=float(noise_floor),
        max_nfev=400,
    )
    fitted = _three_break_prediction(x_ms, tau1_ms, tau2_ms, tau3_ms, result.x)
    residuals = y - fitted
    sse = float(np.sum(residuals * residuals))
    shoulder_slope = float(result.x[1])
    steep_shoulder_slope = float(result.x[1] + result.x[2])
    collapse_slope = float(result.x[1] + result.x[2] + result.x[3])
    tau1_delay = int(round(float(tau1_us)))
    tau2_delay = int(round(float(tau2_us)))
    tau3_delay = int(round(float(tau3_us)))
    breakpoints = [tau1_delay, tau2_delay, tau3_delay]
    return {
        "model_name": MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE,
        "bic": _bic(sse, len(y), 7, noise_floor=noise_floor),
        "sse": sse,
        "params": {
            "width_px": float(result.x[0]),
            "shoulder_slope_px_per_ms": shoulder_slope,
            "steep_shoulder_delta_slope_px_per_ms": float(result.x[2]),
            "steep_shoulder_slope_px_per_ms": steep_shoulder_slope,
            "collapse_delta_slope_px_per_ms": float(result.x[3]),
            "collapse_slope_px_per_ms": collapse_slope,
        },
        "fitted_widths_px": fitted.tolist(),
        "tail_start_delay_from_emergence_us": tau1_delay,
        "knee_delay_from_emergence_us": tau2_delay,
        "second_knee_delay_from_emergence_us": tau3_delay,
        "breakpoint_delays_from_emergence_us": breakpoints,
        "breakpoint_observed_delays": _breakpoint_observed_flags(delays_us, breakpoints),
        "tail_start_observed_delay": _tail_start_observed_delay(delays_us, tau1_delay),
    }


def _refine_three_break(
    best: dict | None,
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
    breakpoint_refinement_step_us: int,
) -> dict | None:
    if best is None or int(breakpoint_refinement_step_us) <= 0:
        return best
    refined = best
    tau1_values = _refinement_values(
        best.get("tail_start_delay_from_emergence_us"),
        delays_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )
    tau2_values = _refinement_values(
        best.get("knee_delay_from_emergence_us"),
        delays_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )
    tau3_values = _refinement_values(
        best.get("second_knee_delay_from_emergence_us"),
        delays_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )
    for tau1_us in tau1_values:
        for tau2_us in tau2_values:
            for tau3_us in tau3_values:
                candidate = _fit_three_break_candidate(
                    delays_us,
                    x_ms,
                    y,
                    tau1_us=float(tau1_us),
                    tau2_us=float(tau2_us),
                    tau3_us=float(tau3_us),
                    noise_floor=noise_floor,
                    min_segment_points=min_segment_points,
                    min_break_gap_us=min_break_gap_us,
                )
                if candidate is not None and float(candidate["bic"]) < float(refined["bic"]):
                    best = candidate
                    refined = candidate
    return refined


def _fit_three_break(
    delays_us: np.ndarray,
    x_ms: np.ndarray,
    y: np.ndarray,
    *,
    noise_floor: float,
    min_segment_points: int,
    min_break_gap_us: int,
    breakpoint_refinement_step_us: int,
) -> dict | None:
    if len(y) < max(8, int(min_segment_points) * 4):
        return None
    best = None
    for tau1_us in delays_us.tolist():
        for tau2_us in delays_us.tolist():
            for tau3_us in delays_us.tolist():
                candidate = _fit_three_break_candidate(
                    delays_us,
                    x_ms,
                    y,
                    tau1_us=float(tau1_us),
                    tau2_us=float(tau2_us),
                    tau3_us=float(tau3_us),
                    noise_floor=noise_floor,
                    min_segment_points=min_segment_points,
                    min_break_gap_us=min_break_gap_us,
                )
                if candidate is not None and (best is None or float(candidate["bic"]) < float(best["bic"])):
                    best = candidate
    return _refine_three_break(
        best,
        delays_us,
        x_ms,
        y,
        noise_floor=noise_floor,
        min_segment_points=min_segment_points,
        min_break_gap_us=min_break_gap_us,
        breakpoint_refinement_step_us=breakpoint_refinement_step_us,
    )


def _fit_points(trace: list[dict], fitted_widths_px: list[float]) -> list[dict]:
    return [
        {
            "delay_from_emergence_us": int(row["delay_from_emergence_us"]),
            "fitted_width_px": float(fitted_widths_px[index]),
        }
        for index, row in enumerate(trace)
    ]


def _empty_three_break_selection_metadata() -> dict:
    return {
        "tail_start_source": TAIL_START_SOURCE_REFERENCE_MODEL,
        "three_break_tail_start_delay_from_emergence_us": None,
        "two_break_tail_start_delay_from_emergence_us": None,
        "midpoint_tail_start_delay_from_emergence_us": None,
        "breakpoint_refinement_step_us": BREAKPOINT_REFINEMENT_STEP_US,
        "tail_start_observed_delay": None,
        "breakpoint_observed_delays": [],
        "three_break_selection_gate": _three_break_selection_gate(
            None,
            two_break=None,
            reference_model=None,
            bic_improvement_threshold=BIC_IMPROVEMENT_THRESHOLD,
        ),
        "local_confirmation": _three_break_local_confirmation(
            [],
            None,
            two_break=None,
            noise_floor=MIN_NOISE_FLOOR_PX,
        ),
    }


def _three_break_selection_gate(
    three_break: dict | None,
    *,
    two_break: dict | None,
    reference_model: dict | None,
    bic_improvement_threshold: float,
) -> dict:
    details = {
        "passed": False,
        "reason": "no_three_break_model",
        "reference_model_name": (
            None if reference_model is None else str(reference_model.get("model_name") or "")
        ),
        "bic_improvement": None,
        "min_bic_improvement": float(bic_improvement_threshold),
        "tail_start_advance_us": None,
        "max_tail_start_advance_us": int(THREE_BREAK_MAX_TAIL_START_ADVANCE_US),
        "early_shoulder_slope_px_per_ms": None,
        "early_shoulder_slope_magnitude_px_per_ms": None,
        "min_early_shoulder_slope_magnitude_px_per_ms": float(
            THREE_BREAK_MIN_EARLY_SHOULDER_SLOPE_PX_PER_MS
        ),
    }
    if three_break is None:
        return details

    details["reason"] = "passed"
    if reference_model is not None:
        reference_bic = _float_or_none(reference_model.get("bic"))
        three_bic = _float_or_none(three_break.get("bic"))
        if reference_bic is not None and three_bic is not None:
            bic_improvement = float(reference_bic) - float(three_bic)
            details["bic_improvement"] = float(bic_improvement)
            if float(bic_improvement) < float(bic_improvement_threshold):
                details["reason"] = "bic_improvement_insufficient"
                return details

    params = dict(three_break.get("params") or {})
    shoulder_slope = _float_or_none(params.get("shoulder_slope_px_per_ms"))
    if shoulder_slope is not None:
        details["early_shoulder_slope_px_per_ms"] = float(shoulder_slope)
        details["early_shoulder_slope_magnitude_px_per_ms"] = abs(float(shoulder_slope))

    if two_break is None:
        details["passed"] = True
        details["reason"] = "no_two_break_reference"
        return details

    three_tail_start = _float_or_none(three_break.get("tail_start_delay_from_emergence_us"))
    two_tail_start = _float_or_none(two_break.get("tail_start_delay_from_emergence_us"))
    if three_tail_start is None or two_tail_start is None:
        details["passed"] = True
        details["reason"] = "missing_tail_start_reference"
        return details

    advance_us = float(two_tail_start) - float(three_tail_start)
    details["tail_start_advance_us"] = float(advance_us)
    if float(advance_us) <= 0.0:
        details["passed"] = True
        return details

    if float(advance_us) > float(THREE_BREAK_MAX_TAIL_START_ADVANCE_US):
        details["reason"] = "tail_start_advance_too_large"
        return details

    shoulder_magnitude = details.get("early_shoulder_slope_magnitude_px_per_ms")
    if shoulder_magnitude is None or float(shoulder_magnitude) < float(
        THREE_BREAK_MIN_EARLY_SHOULDER_SLOPE_PX_PER_MS
    ):
        details["reason"] = "early_shoulder_too_weak"
        return details

    details["passed"] = True
    return details


def _three_break_local_confirmation(
    trace: list[dict],
    three_break: dict | None,
    *,
    two_break: dict | None,
    noise_floor: float,
) -> dict:
    drop_threshold = max(
        float(THREE_BREAK_LOCAL_CONFIRMATION_MIN_DROP_PX),
        float(noise_floor),
    )
    rebound_threshold = max(
        float(THREE_BREAK_LOCAL_CONFIRMATION_MAX_REBOUND_PX),
        float(noise_floor),
    )
    details = {
        "passed": False,
        "reason": "no_three_break_model",
        "baseline_width_px": None,
        "final_drop_px": None,
        "rebound_px": None,
        "drop_threshold_px": float(drop_threshold),
        "rebound_threshold_px": float(rebound_threshold),
        "future_point_count": 0,
    }
    if three_break is None:
        return details

    three_tail_start = _float_or_none(three_break.get("tail_start_delay_from_emergence_us"))
    two_tail_start = (
        None
        if two_break is None
        else _float_or_none(two_break.get("tail_start_delay_from_emergence_us"))
    )
    if three_tail_start is None or two_tail_start is None:
        details["passed"] = True
        details["reason"] = "not_required"
        return details

    advance_us = float(two_tail_start) - float(three_tail_start)
    if float(advance_us) <= 0.0:
        details["passed"] = True
        details["reason"] = "not_required"
        return details

    prior_rows = [
        row
        for row in list(trace or [])
        if (_float_or_none(dict(row or {}).get("delay_from_emergence_us")) is not None)
        and float(dict(row or {}).get("delay_from_emergence_us")) < float(three_tail_start)
    ][-5:]
    prior_widths = [
        _float_or_none(dict(row or {}).get("median_width_px"))
        for row in prior_rows
    ]
    prior_widths = [float(value) for value in prior_widths if value is not None]
    if not prior_widths:
        details["reason"] = "insufficient_pre_tau1_points"
        return details
    baseline = float(statistics.median(prior_widths))
    details["baseline_width_px"] = float(baseline)

    future_rows = [
        row
        for row in list(trace or [])
        if (_float_or_none(dict(row or {}).get("delay_from_emergence_us")) is not None)
        and float(dict(row or {}).get("delay_from_emergence_us")) > float(three_tail_start)
    ][:THREE_BREAK_LOCAL_CONFIRMATION_FUTURE_POINTS]
    future_widths = [
        _float_or_none(dict(row or {}).get("median_width_px"))
        for row in future_rows
    ]
    future_widths = [float(value) for value in future_widths if value is not None]
    details["future_point_count"] = int(len(future_widths))
    if len(future_widths) < int(THREE_BREAK_LOCAL_CONFIRMATION_FUTURE_POINTS):
        details["reason"] = "insufficient_future_points"
        return details

    final_width = float(future_widths[-1])
    local_min_width = float(min(future_widths))
    final_drop = float(baseline - final_width)
    rebound = float(final_width - local_min_width)
    details["final_drop_px"] = float(final_drop)
    details["rebound_px"] = float(rebound)
    if float(final_drop) < float(drop_threshold):
        details["reason"] = "final_drop_too_small"
        return details
    if float(rebound) > float(rebound_threshold):
        details["reason"] = "local_rebound_too_large"
        return details

    details["passed"] = True
    details["reason"] = "passed"
    return details


def _selected_reference_model(
    plateau: dict,
    *,
    one_break: dict | None,
    two_break: dict | None,
    bic_improvement_threshold: float,
) -> dict:
    selected = plateau
    if one_break is not None and float(one_break["bic"]) <= float(selected["bic"]) - float(
        bic_improvement_threshold
    ):
        selected = one_break
    if two_break is not None and float(two_break["bic"]) <= float(selected["bic"]) - float(
        bic_improvement_threshold
    ):
        selected = two_break
    return dict(selected)


def _midpoint_selection(three_break: dict, two_break: dict) -> dict | None:
    three_tail_start = _int_or_none(three_break.get("tail_start_delay_from_emergence_us"))
    two_tail_start = _int_or_none(two_break.get("tail_start_delay_from_emergence_us"))
    if three_tail_start is None or two_tail_start is None:
        return None
    midpoint = _round_to_step_us(
        (float(three_tail_start) + float(two_tail_start)) / 2.0,
        BREAKPOINT_REFINEMENT_STEP_US,
    )
    if midpoint is None:
        return None
    selected = dict(three_break)
    selected["model_name"] = MODEL_THREE_BREAK_TWO_BREAK_MIDPOINT
    selected["tail_start_delay_from_emergence_us"] = int(midpoint)
    selected["breakpoint_delays_from_emergence_us"] = [
        value
        for value in [
            int(midpoint),
            _int_or_none(three_break.get("knee_delay_from_emergence_us")),
            _int_or_none(three_break.get("second_knee_delay_from_emergence_us")),
        ]
        if value is not None
    ]
    return selected


def _select_segmented_tail_model(
    trace: list[dict],
    *,
    plateau: dict,
    one_break: dict | None,
    two_break: dict | None,
    three_break: dict | None,
    noise_floor: float,
    bic_improvement_threshold: float,
) -> dict:
    reference = _selected_reference_model(
        plateau,
        one_break=one_break,
        two_break=two_break,
        bic_improvement_threshold=bic_improvement_threshold,
    )
    hard_gate = _three_break_selection_gate(
        three_break,
        two_break=two_break,
        reference_model=reference,
        bic_improvement_threshold=bic_improvement_threshold,
    )
    local_confirmation = _three_break_local_confirmation(
        trace,
        three_break,
        two_break=two_break,
        noise_floor=noise_floor,
    )
    selected = dict(reference)
    tail_start_source = TAIL_START_SOURCE_REFERENCE_MODEL
    midpoint_tail_start = None

    if three_break is not None and bool(hard_gate.get("passed")):
        if bool(local_confirmation.get("passed")):
            selected = dict(three_break)
            tail_start_source = TAIL_START_SOURCE_THREE_BREAK_TAU1
        elif two_break is not None:
            midpoint_selection = _midpoint_selection(three_break, two_break)
            if midpoint_selection is not None:
                selected = midpoint_selection
                midpoint_tail_start = _int_or_none(
                    selected.get("tail_start_delay_from_emergence_us")
                )
                tail_start_source = TAIL_START_SOURCE_THREE_TWO_MIDPOINT

    return {
        "selected": selected,
        "tail_start_source": tail_start_source,
        "three_break_tail_start_delay_from_emergence_us": (
            None
            if three_break is None
            else _int_or_none(three_break.get("tail_start_delay_from_emergence_us"))
        ),
        "two_break_tail_start_delay_from_emergence_us": (
            None
            if two_break is None
            else _int_or_none(two_break.get("tail_start_delay_from_emergence_us"))
        ),
        "midpoint_tail_start_delay_from_emergence_us": midpoint_tail_start,
        "three_break_selection_gate": hard_gate,
        "local_confirmation": local_confirmation,
    }


def evaluate_segmented_tail_trace(
    tail_rows: list[dict] | None,
    *,
    baseline_width_px: float | int | None = None,
    min_segment_points: int = MIN_SEGMENT_POINTS,
    min_break_gap_us: int = MIN_BREAK_GAP_US,
    breakpoint_refinement_step_us: int = BREAKPOINT_REFINEMENT_STEP_US,
    bic_improvement_threshold: float = BIC_IMPROVEMENT_THRESHOLD,
) -> dict:
    trace = build_tail_width_trace(tail_rows)
    baseline = _float_or_none(baseline_width_px)
    usable_count = len(trace)
    if usable_count < int(min_segment_points) * 2:
        selection_metadata = _empty_three_break_selection_metadata()
        selection_metadata["breakpoint_refinement_step_us"] = int(breakpoint_refinement_step_us)
        return {
            "fit_status": "insufficient_usable_points",
            "model_name": None,
            "tail_start_delay_from_emergence_us": None,
            "knee_delay_from_emergence_us": None,
            "second_knee_delay_from_emergence_us": None,
            "breakpoint_delays_from_emergence_us": [],
            "usable_point_count": int(usable_count),
            "noise_estimate_px": None,
            "bic_scores": {},
            "trace": trace,
            "fit_points": [],
            "models": {},
            **selection_metadata,
        }

    delays_us = np.asarray([int(row["delay_from_emergence_us"]) for row in trace], dtype=float)
    widths = np.asarray([float(row["median_width_px"]) for row in trace], dtype=float)
    x_ms = (delays_us - delays_us[0]) / 1000.0
    noise_floor = _estimate_noise_px(widths, baseline_width_px=baseline)

    try:
        plateau = _plateau_fit(widths, noise_floor=noise_floor)
        one_break = _fit_one_break(
            delays_us,
            x_ms,
            widths,
            noise_floor=noise_floor,
            min_segment_points=min_segment_points,
            min_break_gap_us=min_break_gap_us,
            breakpoint_refinement_step_us=breakpoint_refinement_step_us,
        )
        two_break = _fit_two_break(
            delays_us,
            x_ms,
            widths,
            noise_floor=noise_floor,
            min_segment_points=min_segment_points,
            min_break_gap_us=min_break_gap_us,
            breakpoint_refinement_step_us=breakpoint_refinement_step_us,
        )
        three_break = _fit_three_break(
            delays_us,
            x_ms,
            widths,
            noise_floor=noise_floor,
            min_segment_points=min_segment_points,
            min_break_gap_us=min_break_gap_us,
            breakpoint_refinement_step_us=breakpoint_refinement_step_us,
        )
    except Exception as exc:
        selection_metadata = _empty_three_break_selection_metadata()
        selection_metadata["breakpoint_refinement_step_us"] = int(breakpoint_refinement_step_us)
        return {
            "fit_status": "fit_failed",
            "fit_error": str(exc),
            "model_name": None,
            "tail_start_delay_from_emergence_us": None,
            "knee_delay_from_emergence_us": None,
            "second_knee_delay_from_emergence_us": None,
            "breakpoint_delays_from_emergence_us": [],
            "usable_point_count": int(usable_count),
            "noise_estimate_px": float(noise_floor),
            "bic_scores": {},
            "trace": trace,
            "fit_points": [],
            "models": {},
            **selection_metadata,
        }

    models = {MODEL_PLATEAU: plateau}
    if one_break is not None:
        models[MODEL_PLATEAU_DECLINE] = one_break
    if two_break is not None:
        models[MODEL_PLATEAU_SHOULDER_COLLAPSE] = two_break
    if three_break is not None:
        models[MODEL_PLATEAU_GRADUAL_SHOULDER_STEEP_SHOULDER_COLLAPSE] = three_break

    selection = _select_segmented_tail_model(
        trace,
        plateau=plateau,
        one_break=one_break,
        two_break=two_break,
        three_break=three_break,
        noise_floor=float(noise_floor),
        bic_improvement_threshold=float(bic_improvement_threshold),
    )
    selected = dict(selection["selected"])
    selected_breakpoints = [
        int(value)
        for value in list(selected.get("breakpoint_delays_from_emergence_us") or [])
        if _int_or_none(value) is not None
    ]
    selected_observed_flags = _breakpoint_observed_flags(delays_us, selected_breakpoints)
    fit_points = _fit_points(trace, list(selected.get("fitted_widths_px") or []))
    return {
        "fit_status": "ok",
        "model_name": selected.get("model_name"),
        "tail_start_delay_from_emergence_us": _int_or_none(
            selected.get("tail_start_delay_from_emergence_us")
        ),
        "knee_delay_from_emergence_us": _int_or_none(
            selected.get("knee_delay_from_emergence_us")
        ),
        "second_knee_delay_from_emergence_us": _int_or_none(
            selected.get("second_knee_delay_from_emergence_us")
        ),
        "breakpoint_delays_from_emergence_us": selected_breakpoints,
        "usable_point_count": int(usable_count),
        "noise_estimate_px": float(noise_floor),
        "bic_scores": {
            name: float(model["bic"])
            for name, model in models.items()
            if _float_or_none(model.get("bic")) is not None
        },
        "trace": trace,
        "fit_points": fit_points,
        "tail_start_source": selection.get("tail_start_source"),
        "three_break_tail_start_delay_from_emergence_us": _int_or_none(
            selection.get("three_break_tail_start_delay_from_emergence_us")
        ),
        "two_break_tail_start_delay_from_emergence_us": _int_or_none(
            selection.get("two_break_tail_start_delay_from_emergence_us")
        ),
        "midpoint_tail_start_delay_from_emergence_us": _int_or_none(
            selection.get("midpoint_tail_start_delay_from_emergence_us")
        ),
        "breakpoint_refinement_step_us": int(breakpoint_refinement_step_us),
        "tail_start_observed_delay": _tail_start_observed_delay(
            delays_us,
            selected.get("tail_start_delay_from_emergence_us"),
        ),
        "breakpoint_observed_delays": selected_observed_flags,
        "three_break_selection_gate": dict(selection.get("three_break_selection_gate") or {}),
        "local_confirmation": dict(selection.get("local_confirmation") or {}),
        "models": {
            name: {
                key: value
                for key, value in dict(model).items()
                if key not in {"fitted_widths_px"}
            }
            for name, model in models.items()
        },
    }
