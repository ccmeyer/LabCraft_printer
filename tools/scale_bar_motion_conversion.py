from __future__ import annotations

import argparse
import csv
import html
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np

try:
    from scipy.signal import find_peaks
except Exception:  # pragma: no cover - scipy is a project dependency, keep import robust.
    find_peaks = None


IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"}
MOTION_MIN_FIT_COUNT = 20
MOTION_MIN_REPEAT_GROUPS = 3
MOTION_MAX_RMSE_2D_PX = 15.0
MOTION_MAX_P95_2D_RESIDUAL_PX = 25.0
METADATA_FIELDS = (
    "index",
    "saved_at",
    "X_position",
    "Y_position",
    "Z_position",
    "position_source",
    "position_recorded_at",
    "capture_context",
    "commands_idle_at_frame",
    "machine_position",
    "controller_expected_position",
)


@dataclass(frozen=True)
class ScaleBarMotionOptions:
    min_main_peaks: int = 80
    min_spine_long: float = 580.0
    min_y_profile_height_px: float = 580.0
    max_spacing_cv_pct: float = 20.0
    max_x_disagreement_px: float = 20.0
    max_angle_from_vertical_deg: float = 12.0
    roi_half_width_px: int = 130
    spine_threshold_start: int = 150
    spine_threshold_stop: int = 270
    spine_threshold_step: int = 30
    spine_min_area: float = 1000.0
    spine_min_aspect: float = 4.0
    spine_border_px: int = 150
    center_x_source: str = "column_profile_centroid"
    center_y_source: str = "row_profile_bounds"
    x_profile_threshold_fraction: float = 0.20
    x_profile_min_width_px: float = 10.0
    y_profile_threshold_fraction: float = 0.20

    @classmethod
    def from_value(cls, value: ScaleBarMotionOptions | dict[str, Any] | None) -> "ScaleBarMotionOptions":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        allowed = set(cls.__dataclass_fields__.keys())
        return cls(**{key: val for key, val in dict(value).items() if key in allowed})


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def _finite_float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _normalize_angle_deg(angle: float) -> float:
    while angle > 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return float(angle)


def _contour_angle_from_vertical(contour: np.ndarray) -> float:
    points = contour.reshape(-1, 2).astype(np.float32)
    if len(points) < 3:
        return 0.0
    points -= points.mean(axis=0)
    cov = np.cov(points.T)
    if not np.all(np.isfinite(cov)):
        return 0.0
    _eigvals, eigvecs = np.linalg.eigh(cov)
    vx, vy = eigvecs[:, -1]
    angle_from_x = math.degrees(math.atan2(float(vy), float(vx)))
    return _normalize_angle_deg(angle_from_x - 90.0)


def _safe_spacing_cv(spacings: np.ndarray) -> float:
    if spacings.size <= 1:
        return 0.0
    mean = float(np.mean(spacings))
    if mean <= 0:
        return 999.0
    return float(np.std(spacings, ddof=1) / mean * 100.0)


def _local_contrast(gray: np.ndarray) -> dict[str, Any]:
    h, w = gray.shape[:2]
    sigma = max(9.0, min(h, w) * 0.035)
    background = cv2.GaussianBlur(gray, (0, 0), sigma)
    contrast = cv2.absdiff(gray, background)
    threshold = max(12.0, float(np.percentile(contrast, 98.7)))
    binary = (contrast >= threshold).astype(np.uint8) * 255
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
    return {
        "background": background,
        "contrast": contrast,
        "threshold": float(threshold),
        "binary": binary,
    }


def _find_signal_peaks(signal: np.ndarray) -> np.ndarray:
    if signal.size < 3 or float(signal.max(initial=0.0)) <= 0.0:
        return np.array([], dtype=int)
    signal = signal.astype(np.float32)
    kernel_width = max(3, min(21, int(round(signal.size * 0.006)) | 1))
    smooth = cv2.GaussianBlur(signal.reshape(1, -1), (kernel_width, 1), 0).ravel()
    distance = int(max(3, round(signal.size * 0.003)))
    height = max(3.0, float(np.percentile(smooth, 85)) * 0.45, float(smooth.max()) * 0.18)
    if find_peaks is not None:
        peaks, _props = find_peaks(
            smooth,
            height=height,
            distance=distance,
            prominence=max(1.0, height * 0.25),
        )
        return peaks.astype(int)

    peaks = []
    for idx in range(1, len(smooth) - 1):
        if smooth[idx] >= height and smooth[idx] >= smooth[idx - 1] and smooth[idx] > smooth[idx + 1]:
            if peaks and (idx - peaks[-1]) < distance:
                if smooth[idx] > smooth[peaks[-1]]:
                    peaks[-1] = idx
            else:
                peaks.append(idx)
    return np.asarray(peaks, dtype=int)


def _accepted_tick_sequence(peaks: np.ndarray) -> dict[str, Any]:
    if peaks.size < 2:
        return {
            "accepted_peaks": np.array([], dtype=int),
            "spacing_median": None,
            "spacing_cv_pct": None,
            "accepted_spacings_px": [],
        }

    peaks = np.sort(peaks.astype(int))
    diffs = np.diff(peaks).astype(float)
    local_diffs = diffs[(diffs > 0) & (diffs <= np.percentile(diffs, 75) * 1.5)]
    if local_diffs.size == 0:
        local_diffs = diffs[diffs > 0]
    spacing_median = float(np.median(local_diffs)) if local_diffs.size else None
    if not spacing_median or spacing_median <= 0:
        return {
            "accepted_peaks": np.array([], dtype=int),
            "spacing_median": None,
            "spacing_cv_pct": None,
            "accepted_spacings_px": [],
        }

    max_neighbor_gap = max(2.0, spacing_median * 2.8)
    keep = []
    for idx, peak in enumerate(peaks):
        left = float(peak - peaks[idx - 1]) if idx > 0 else float("inf")
        right = float(peaks[idx + 1] - peak) if idx < len(peaks) - 1 else float("inf")
        if min(left, right) <= max_neighbor_gap:
            keep.append(int(peak))
    accepted = np.asarray(keep, dtype=int)
    if accepted.size < 2:
        accepted = peaks

    accepted_diffs = np.diff(accepted).astype(float)
    close_diffs = accepted_diffs[
        (accepted_diffs >= max(2.0, spacing_median * 0.55))
        & (accepted_diffs <= max(3.0, spacing_median * 1.65))
    ]
    if close_diffs.size == 0:
        close_diffs = accepted_diffs[accepted_diffs > 0]

    return {
        "accepted_peaks": accepted,
        "spacing_median": float(spacing_median),
        "spacing_cv_pct": _safe_spacing_cv(close_diffs),
        "accepted_spacings_px": [float(v) for v in close_diffs.tolist()],
    }


def _profile_support_center(
    signal: np.ndarray,
    *,
    threshold_fraction: float,
    offset: int = 0,
) -> dict[str, Any] | None:
    if signal.size == 0 or float(signal.max(initial=0.0)) <= 0.0:
        return None
    signal = signal.astype(np.float32)
    kernel_width = max(3, min(31, int(round(signal.size * 0.04)) | 1))
    smooth = cv2.GaussianBlur(signal.reshape(1, -1), (kernel_width, 1), 0).ravel()
    threshold = max(3.0, float(smooth.max()) * float(threshold_fraction))
    support = np.flatnonzero(smooth >= threshold)
    if support.size == 0:
        return None
    left = int(support[0])
    right = int(support[-1])
    support_signal = np.maximum(smooth[left : right + 1] - threshold, 0.0)
    coords = np.arange(left, right + 1, dtype=np.float32)
    if float(support_signal.sum()) > 0.0:
        centroid = float(np.sum(coords * support_signal) / np.sum(support_signal))
    else:
        centroid = float((left + right) / 2.0)
    return {
        "signal": signal,
        "smooth_signal": smooth,
        "threshold": float(threshold),
        "left": int(left + offset),
        "right": int(right + offset),
        "center_bounds": float((left + right) / 2.0 + offset),
        "center_centroid": float(centroid + offset),
        "width": float(right - left + 1),
    }


def _detect_spine(gray: np.ndarray, options: ScaleBarMotionOptions) -> dict[str, Any] | None:
    blurred = cv2.GaussianBlur(gray, (15, 15), 0)
    h, w = gray.shape[:2]
    dynamic_border = min(float(options.spine_border_px), max(10.0, min(h, w) * 0.12))
    best = None

    for threshold_value in range(
        int(options.spine_threshold_start),
        int(options.spine_threshold_stop) + 1,
        int(options.spine_threshold_step),
    ):
        _threshold, dark_mask = cv2.threshold(blurred, threshold_value, 255, cv2.THRESH_BINARY_INV)
        eroded = cv2.erode(dark_mask, np.ones((10, 10), np.uint8), iterations=3)
        contours, _hierarchy = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < float(options.spine_min_area):
                continue
            moments = cv2.moments(contour)
            if moments["m00"] == 0:
                continue
            centroid_x = float(moments["m10"] / moments["m00"])
            centroid_y = float(moments["m01"] / moments["m00"])
            if not (
                dynamic_border < centroid_x < (w - dynamic_border)
                and dynamic_border < centroid_y < (h - dynamic_border)
            ):
                continue

            rect = cv2.minAreaRect(contour)
            (rect_cx, rect_cy), (rect_w, rect_h), rect_angle = rect
            long_side = float(max(rect_w, rect_h))
            short_side = float(max(1.0, min(rect_w, rect_h)))
            aspect = long_side / short_side
            if aspect < float(options.spine_min_aspect):
                continue

            x, y, bw, bh = cv2.boundingRect(contour)
            angle_from_vertical = _contour_angle_from_vertical(contour)
            score = area * aspect
            candidate = {
                "threshold": int(threshold_value),
                "dark_mask": dark_mask,
                "eroded_mask": eroded,
                "contour": contour,
                "rect": rect,
                "rect_box": cv2.boxPoints(rect),
                "spine_rect_x": float(rect_cx),
                "spine_rect_y": float(rect_cy),
                "spine_centroid_x": float(centroid_x),
                "spine_centroid_y": float(centroid_y),
                "spine_bbox_x": float(x + bw / 2.0),
                "spine_bbox_y": float(y + bh / 2.0),
                "spine_bbox": [int(x), int(y), int(bw), int(bh)],
                "spine_area": float(area),
                "spine_long_px": float(long_side),
                "spine_short_px": float(short_side),
                "spine_aspect": float(aspect),
                "spine_angle_from_vertical_deg": float(angle_from_vertical),
                "score": float(score),
            }
            if best is None or score > best["score"]:
                best = candidate

        if best is not None:
            return best
    return best


def _detect_ticks_near_spine(
    gray: np.ndarray,
    spine: dict[str, Any],
    options: ScaleBarMotionOptions,
) -> dict[str, Any] | None:
    local = _local_contrast(gray)
    binary = local["binary"]
    h, w = binary.shape[:2]
    center_x = float(spine["spine_bbox_x"])
    roi_x0 = max(0, int(round(center_x - int(options.roi_half_width_px))))
    roi_x1 = min(w, int(round(center_x + int(options.roi_half_width_px))))
    if roi_x1 <= roi_x0:
        return None

    roi_mask = binary[:, roi_x0:roi_x1]
    signal = roi_mask.sum(axis=1).astype(np.float32) / 255.0
    y_profile = _profile_support_center(
        signal,
        threshold_fraction=float(options.y_profile_threshold_fraction),
        offset=0,
    )
    if y_profile is not None:
        y_profile.update(
            {
                "mask": roi_mask,
                "source": "local_contrast_row_sum",
            }
        )

    peaks = _find_signal_peaks(signal)
    sequence = _accepted_tick_sequence(peaks)
    accepted_peaks = sequence["accepted_peaks"]
    if accepted_peaks.size:
        first_peak = int(accepted_peaks[0])
        last_peak = int(accepted_peaks[-1])
    else:
        first_peak = None
        last_peak = None

    x_profile = None
    if y_profile is not None:
        spacing = sequence.get("spacing_median")
        y_pad = int(max(8, round(float(spacing or 6.0) * 2.0)))
        profile_y0 = max(0, int(y_profile["left"]) - y_pad)
        profile_y1 = min(h, int(y_profile["right"]) + y_pad + 1)
        dark_roi = spine["dark_mask"][profile_y0:profile_y1, roi_x0:roi_x1]
        dark_col_signal = dark_roi.sum(axis=0).astype(np.float32) / 255.0
        x_profile = _profile_support_center(
            dark_col_signal,
            threshold_fraction=float(options.x_profile_threshold_fraction),
            offset=roi_x0,
        )
        if x_profile is not None:
            x_profile.update(
                {
                    "mask": dark_roi,
                    "y0": int(profile_y0),
                    "y1": int(profile_y1),
                    "source": "dark_mask_column_sum",
                }
            )

    return {
        "local_contrast_threshold": float(local["threshold"]),
        "local_contrast_binary": binary,
        "local_contrast_roi_mask": roi_mask,
        "tick_signal": signal,
        "tick_peaks": peaks,
        "accepted_tick_peaks": accepted_peaks,
        "tick_peak_count": int(peaks.size),
        "main_peak_count": int(accepted_peaks.size),
        "main_first_peak_y": first_peak,
        "main_last_peak_y": last_peak,
        "tick_spacing_median_px": sequence["spacing_median"],
        "tick_spacing_cv_pct": sequence["spacing_cv_pct"],
        "accepted_tick_spacings_px": sequence["accepted_spacings_px"],
        "roi_x0": int(roi_x0),
        "roi_x1": int(roi_x1),
        "roi_clipped": bool(roi_x0 == 0 or roi_x1 == w),
        "center_y": _center_y_from_detection({"y_profile": y_profile}, options.center_y_source),
        "center_y_source": options.center_y_source,
        "y_profile": y_profile,
        "x_profile": x_profile,
    }


def _center_x_from_detection(spine: dict[str, Any], ticks: dict[str, Any], source: str) -> float | None:
    x_profile = ticks.get("x_profile")
    if source == "column_profile_centroid":
        return None if x_profile is None else float(x_profile["center_centroid"])
    if source == "column_profile_bounds":
        return None if x_profile is None else float(x_profile["center_bounds"])
    key = {
        "spine_rect": "spine_rect_x",
        "spine_bbox": "spine_bbox_x",
        "spine_centroid": "spine_centroid_x",
    }.get(source, "spine_bbox_x")
    return float(spine[key])


def _center_y_from_detection(ticks: dict[str, Any], source: str) -> float | None:
    y_profile = ticks.get("y_profile")
    if y_profile is None:
        return None
    if source == "row_profile_centroid":
        return float(y_profile["center_centroid"])
    return float(y_profile["center_bounds"])


def _quality_flags(spine: dict[str, Any], ticks: dict[str, Any], options: ScaleBarMotionOptions) -> list[str]:
    flags = []
    if abs(float(spine["spine_angle_from_vertical_deg"])) > float(options.max_angle_from_vertical_deg):
        flags.append("spine_angle_large")
    if bool(ticks["roi_clipped"]):
        flags.append("roi_clipped")

    y_profile = ticks.get("y_profile")
    if y_profile is None:
        flags.append("y_profile_not_found")
    elif float(y_profile["width"]) < float(options.min_y_profile_height_px):
        flags.append("y_profile_too_short")

    x_profile = ticks.get("x_profile")
    if x_profile is None:
        flags.append("x_profile_not_found")
    elif float(x_profile["width"]) < float(options.x_profile_min_width_px):
        flags.append("x_profile_too_narrow")

    return flags


def _warning_flags(spine: dict[str, Any], ticks: dict[str, Any], options: ScaleBarMotionOptions) -> list[str]:
    flags = []
    if float(spine["spine_long_px"]) < float(options.min_spine_long):
        flags.append("spine_too_short")
    if int(ticks.get("main_peak_count", 0)) < int(options.min_main_peaks):
        flags.append("too_few_main_peaks")
    spacing_cv = ticks.get("tick_spacing_cv_pct")
    if spacing_cv is None or float(spacing_cv) > float(options.max_spacing_cv_pct):
        flags.append("inconsistent_tick_spacing")
    return flags


def _metadata_subset(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {field: metadata.get(field) for field in METADATA_FIELDS if field in metadata}


def _analyze_image_internal(
    path: str | Path,
    *,
    metadata: dict[str, Any] | None = None,
    options: ScaleBarMotionOptions | dict[str, Any] | None = None,
    include_debug: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    image_path = Path(path)
    opts = ScaleBarMotionOptions.from_value(options)
    bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if bgr is None:
        result = {
            "path": str(image_path),
            "filename": image_path.name,
            "status": "error",
            "error": "image_read_failed",
        }
        result.update(_metadata_subset(metadata))
        return result, {}

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    debug = {"bgr": bgr, "rgb": cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), "gray": gray} if include_debug else {}

    spine = _detect_spine(gray, opts)
    if spine is None:
        result = {
            "path": str(image_path),
            "filename": image_path.name,
            "status": "error",
            "error": "spine_not_found",
            "quality_flags": ["spine_not_found"],
            "image_shape": [int(gray.shape[0]), int(gray.shape[1])],
        }
        result.update(_metadata_subset(metadata))
        return result, debug

    ticks = _detect_ticks_near_spine(gray, spine, opts)
    if ticks is None or ticks.get("center_y") is None:
        result = {
            "path": str(image_path),
            "filename": image_path.name,
            "status": "error",
            "error": "tick_sequence_not_found",
            "quality_flags": ["tick_sequence_not_found"],
            "image_shape": [int(gray.shape[0]), int(gray.shape[1])],
            **_serializable_spine(spine),
        }
        result.update(_metadata_subset(metadata))
        if include_debug:
            debug.update({"spine": spine})
        return result, debug

    center_x = _center_x_from_detection(spine, ticks, opts.center_x_source)
    if center_x is None:
        result = {
            "path": str(image_path),
            "filename": image_path.name,
            "status": "error",
            "error": "x_profile_not_found",
            "quality_flags": ["x_profile_not_found"],
            "image_shape": [int(gray.shape[0]), int(gray.shape[1])],
            **_serializable_spine(spine),
        }
        result.update(_metadata_subset(metadata))
        if include_debug:
            debug.update({"spine": spine, "ticks": ticks})
        return result, debug
    center_y = float(ticks["center_y"])
    flags = _quality_flags(spine, ticks, opts)
    warnings = _warning_flags(spine, ticks, opts)
    x_profile = ticks.get("x_profile") or {}
    x_profile_disagreement = None
    if x_profile:
        x_profile_disagreement = abs(float(x_profile["center_bounds"]) - float(x_profile["center_centroid"]))
    y_profile = ticks.get("y_profile") or {}
    y_profile_disagreement = None
    if y_profile:
        y_profile_disagreement = abs(float(y_profile["center_bounds"]) - float(y_profile["center_centroid"]))
    result = {
        "path": str(image_path),
        "filename": image_path.name,
        "status": "ok" if not flags else "rejected",
        "error": None if not flags else "quality_flags",
        "quality_flags": flags,
        "warning_flags": warnings,
        "center_x": float(center_x),
        "center_y": float(center_y),
        "center_x_source": opts.center_x_source,
        "center_y_source": ticks["center_y_source"],
        "spine_rect_x": float(spine["spine_rect_x"]),
        "spine_rect_y": float(spine["spine_rect_y"]),
        "spine_bbox_x": float(spine["spine_bbox_x"]),
        "spine_bbox_y": float(spine["spine_bbox_y"]),
        "spine_centroid_x": float(spine["spine_centroid_x"]),
        "spine_centroid_y": float(spine["spine_centroid_y"]),
        "spine_x_disagreement_px": float(
            max(spine["spine_rect_x"], spine["spine_bbox_x"], spine["spine_centroid_x"])
            - min(spine["spine_rect_x"], spine["spine_bbox_x"], spine["spine_centroid_x"])
        ),
        "x_profile_center_bounds": None if not x_profile else float(x_profile["center_bounds"]),
        "x_profile_center_centroid": None if not x_profile else float(x_profile["center_centroid"]),
        "x_profile_left_x": None if not x_profile else int(x_profile["left"]),
        "x_profile_right_x": None if not x_profile else int(x_profile["right"]),
        "x_profile_width_px": None if not x_profile else float(x_profile["width"]),
        "x_profile_threshold": None if not x_profile else float(x_profile["threshold"]),
        "x_profile_y0": None if not x_profile else int(x_profile["y0"]),
        "x_profile_y1": None if not x_profile else int(x_profile["y1"]),
        "x_profile_source": None if not x_profile else str(x_profile["source"]),
        "x_profile_disagreement_px": x_profile_disagreement,
        "y_profile_center_bounds": None if not y_profile else float(y_profile["center_bounds"]),
        "y_profile_center_centroid": None if not y_profile else float(y_profile["center_centroid"]),
        "y_profile_top_y": None if not y_profile else int(y_profile["left"]),
        "y_profile_bottom_y": None if not y_profile else int(y_profile["right"]),
        "y_profile_height_px": None if not y_profile else float(y_profile["width"]),
        "y_profile_threshold": None if not y_profile else float(y_profile["threshold"]),
        "y_profile_source": None if not y_profile else str(y_profile["source"]),
        "y_profile_disagreement_px": y_profile_disagreement,
        "spine_bbox": list(spine["spine_bbox"]),
        "spine_area": float(spine["spine_area"]),
        "spine_long_px": float(spine["spine_long_px"]),
        "spine_short_px": float(spine["spine_short_px"]),
        "spine_aspect": float(spine["spine_aspect"]),
        "spine_angle_from_vertical_deg": float(spine["spine_angle_from_vertical_deg"]),
        "spine_threshold": int(spine["threshold"]),
        "roi_x0": int(ticks["roi_x0"]),
        "roi_x1": int(ticks["roi_x1"]),
        "roi_clipped": bool(ticks["roi_clipped"]),
        "tick_peak_count": int(ticks["tick_peak_count"]),
        "main_peak_count": int(ticks["main_peak_count"]),
        "main_first_peak_y": ticks["main_first_peak_y"],
        "main_last_peak_y": ticks["main_last_peak_y"],
        "tick_spacing_median_px": ticks["tick_spacing_median_px"],
        "tick_spacing_cv_pct": ticks["tick_spacing_cv_pct"],
        "accepted_tick_spacings_px": ticks["accepted_tick_spacings_px"],
        "local_contrast_threshold": float(ticks["local_contrast_threshold"]),
        "image_shape": [int(gray.shape[0]), int(gray.shape[1])],
    }
    result.update(_metadata_subset(metadata))
    if include_debug:
        debug.update({"spine": spine, "ticks": ticks})
    return result, debug


def _serializable_spine(spine: dict[str, Any]) -> dict[str, Any]:
    return {
        "spine_rect_x": float(spine["spine_rect_x"]),
        "spine_rect_y": float(spine["spine_rect_y"]),
        "spine_bbox_x": float(spine["spine_bbox_x"]),
        "spine_bbox_y": float(spine["spine_bbox_y"]),
        "spine_centroid_x": float(spine["spine_centroid_x"]),
        "spine_centroid_y": float(spine["spine_centroid_y"]),
        "spine_bbox": list(spine["spine_bbox"]),
        "spine_area": float(spine["spine_area"]),
        "spine_long_px": float(spine["spine_long_px"]),
        "spine_short_px": float(spine["spine_short_px"]),
        "spine_aspect": float(spine["spine_aspect"]),
        "spine_angle_from_vertical_deg": float(spine["spine_angle_from_vertical_deg"]),
        "spine_threshold": int(spine["threshold"]),
    }


def analyze_scale_bar_center_image(
    path: str | Path,
    metadata: dict[str, Any] | None = None,
    options: ScaleBarMotionOptions | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract a hybrid scale-bar center from one image."""
    result, _debug = _analyze_image_internal(path, metadata=metadata, options=options, include_debug=False)
    return result


def _load_metadata_by_filename(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            filename = row.get("filename")
            if filename:
                rows[str(filename)] = row
    return rows


def _regression_eligible(row: dict[str, Any]) -> bool:
    if row.get("status") != "ok":
        return False
    if row.get("commands_idle_at_frame") is not True:
        return False
    return (
        _finite_float(row.get("X_position")) is not None
        and _finite_float(row.get("Z_position")) is not None
        and _finite_float(row.get("center_x")) is not None
        and _finite_float(row.get("center_y")) is not None
    )


def _mark_manual_rejection(row: dict[str, Any]) -> dict[str, Any]:
    flags = list(row.get("quality_flags") or [])
    if "manual_rejected" not in flags:
        flags.append("manual_rejected")
    row["status"] = "rejected"
    row["error"] = "manual_rejected"
    row["quality_flags"] = flags
    row["used_for_motion_fit"] = False
    return row


def _fit_motion(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    fit_rows = [row for row in rows if _regression_eligible(row)]
    if len(fit_rows) < 3:
        return None

    xz = np.asarray([[float(row["X_position"]), float(row["Z_position"])] for row in fit_rows], dtype=float)
    centers = np.asarray([[float(row["center_x"]), float(row["center_y"])] for row in fit_rows], dtype=float)
    design = np.column_stack([np.ones(len(fit_rows)), xz])
    coef_x, *_ = np.linalg.lstsq(design, centers[:, 0], rcond=None)
    coef_y, *_ = np.linalg.lstsq(design, centers[:, 1], rcond=None)
    pred_x = design @ coef_x
    pred_y = design @ coef_y
    residuals = centers - np.column_stack([pred_x, pred_y])
    residual_norm = np.linalg.norm(residuals, axis=1)

    for idx, row in enumerate(fit_rows):
        row["predicted_center_x"] = float(pred_x[idx])
        row["predicted_center_y"] = float(pred_y[idx])
        row["residual_x_px"] = float(residuals[idx, 0])
        row["residual_y_px"] = float(residuals[idx, 1])
        row["residual_norm_px"] = float(residual_norm[idx])
        row["used_for_motion_fit"] = True

    matrix = np.asarray([[float(coef_x[1]), float(coef_x[2])], [float(coef_y[1]), float(coef_y[2])]], dtype=float)
    determinant = float(np.linalg.det(matrix))
    inverse = np.linalg.inv(matrix).tolist() if abs(determinant) > 1e-12 else None

    return {
        "status": "ok",
        "fit_count": int(len(fit_rows)),
        "intercept": [float(coef_x[0]), float(coef_y[0])],
        "matrix": matrix.tolist(),
        "inverse_matrix": inverse,
        "determinant": determinant,
        "rmse_x_px": float(np.sqrt(np.mean(residuals[:, 0] ** 2))),
        "rmse_y_px": float(np.sqrt(np.mean(residuals[:, 1] ** 2))),
        "rmse_2d_px": float(np.sqrt(np.mean(residual_norm**2))),
        "median_2d_residual_px": float(np.median(residual_norm)),
        "p95_2d_residual_px": float(np.percentile(residual_norm, 95)),
        "max_2d_residual_px": float(np.max(residual_norm)),
    }


def summarize_motion_fit_quality(
    payload: dict[str, Any],
    *,
    min_fit_count: int = MOTION_MIN_FIT_COUNT,
    min_repeat_groups: int = MOTION_MIN_REPEAT_GROUPS,
    max_rmse_2d_px: float = MOTION_MAX_RMSE_2D_PX,
    max_p95_2d_residual_px: float = MOTION_MAX_P95_2D_RESIDUAL_PX,
) -> dict[str, Any]:
    """Return compact apply-gate status for a motion-conversion analysis payload."""
    summary = dict((payload or {}).get("summary") or {})
    fit = dict((payload or {}).get("motion_fit") or {})
    failed = []

    fit_count = int(fit.get("fit_count") or summary.get("motion_fit_count") or 0)
    repeat_group_count = int(summary.get("repeat_position_group_count") or 0)
    rmse_2d = _finite_float(fit.get("rmse_2d_px"))
    p95_2d = _finite_float(fit.get("p95_2d_residual_px"))
    determinant = _finite_float(fit.get("determinant"))
    matrix = fit.get("matrix")
    try:
        matrix_arr = np.asarray(matrix, dtype=float)
    except Exception:
        matrix_arr = np.asarray([])
    matrix_valid = bool(matrix_arr.shape == (2, 2) and np.all(np.isfinite(matrix_arr)))

    if fit.get("status") != "ok":
        failed.append("motion_fit_failed")
    if fit_count < int(min_fit_count):
        failed.append(f"fit_count<{int(min_fit_count)}")
    if repeat_group_count < int(min_repeat_groups):
        failed.append(f"repeat_groups<{int(min_repeat_groups)}")
    if not matrix_valid:
        failed.append("matrix_invalid")
    if determinant is None or abs(float(determinant)) <= 1e-12:
        failed.append("matrix_not_invertible")
    if rmse_2d is None or float(rmse_2d) > float(max_rmse_2d_px):
        failed.append(f"rmse_2d>{float(max_rmse_2d_px):g}")
    if p95_2d is None or float(p95_2d) > float(max_p95_2d_residual_px):
        failed.append(f"p95_2d>{float(max_p95_2d_residual_px):g}")

    return {
        "schema_version": 1,
        "status": "ok" if not failed else "failed",
        "apply_ready": not failed,
        "failed_criteria": failed,
        "fit_count": int(fit_count),
        "repeat_position_group_count": int(repeat_group_count),
        "rmse_2d_px": rmse_2d,
        "p95_2d_residual_px": p95_2d,
        "determinant": determinant,
        "thresholds": {
            "min_fit_count": int(min_fit_count),
            "min_repeat_groups": int(min_repeat_groups),
            "max_rmse_2d_px": float(max_rmse_2d_px),
            "max_p95_2d_residual_px": float(max_p95_2d_residual_px),
        },
    }


def _repeat_position_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        x = _finite_float(row.get("X_position"))
        z = _finite_float(row.get("Z_position"))
        if x is None or z is None:
            continue
        groups.setdefault((int(round(x)), int(round(z))), []).append(row)

    out = []
    for (x, z), items in groups.items():
        if len(items) < 2:
            continue
        xs = np.asarray([float(row["center_x"]) for row in items], dtype=float)
        ys = np.asarray([float(row["center_y"]) for row in items], dtype=float)
        out.append(
            {
                "X_position": int(x),
                "Z_position": int(z),
                "n": int(len(items)),
                "x_std_px": float(np.std(xs, ddof=1)),
                "y_std_px": float(np.std(ys, ddof=1)),
                "x_range_px": float(np.max(xs) - np.min(xs)),
                "y_range_px": float(np.max(ys) - np.min(ys)),
                "filenames": [str(row["filename"]) for row in sorted(items, key=lambda r: r["filename"])],
            }
        )
    return sorted(out, key=lambda row: (float(row["x_std_px"]), float(row["y_std_px"])), reverse=True)


def _select_image_paths(paths: list[Path], image_limit: int | None = None) -> list[Path]:
    if image_limit is None or int(image_limit) <= 0 or len(paths) <= int(image_limit):
        return paths
    count = int(image_limit)
    indices = np.linspace(0, len(paths) - 1, count)
    selected_indices = sorted({int(round(value)) for value in indices})
    idx = 0
    while len(selected_indices) < count and idx < len(paths):
        if idx not in selected_indices:
            selected_indices.append(idx)
        idx += 1
    return [paths[index] for index in sorted(selected_indices[:count])]


def analyze_scale_bar_motion_directory(
    path: str | Path,
    options: ScaleBarMotionOptions | dict[str, Any] | None = None,
    metadata_filename: str = "metadata.jsonl",
    image_limit: int | None = None,
    rejected_filenames: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Analyze a capture directory and fit scale-bar center against machine X/Z."""
    directory = Path(path)
    if not directory.exists() or not directory.is_dir():
        raise FileNotFoundError(f"Scale-bar capture directory does not exist: {directory}")
    opts = ScaleBarMotionOptions.from_value(options)
    metadata_path = directory / str(metadata_filename)
    metadata_by_filename = _load_metadata_by_filename(metadata_path)
    all_image_paths = sorted(p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    image_paths = _select_image_paths(all_image_paths, image_limit=image_limit)
    rejected_names = {Path(str(name)).name for name in (rejected_filenames or [])}

    results = []
    for image_path in image_paths:
        metadata = metadata_by_filename.get(image_path.name)
        row = analyze_scale_bar_center_image(image_path, metadata=metadata, options=opts)
        if image_path.name in rejected_names:
            row = _mark_manual_rejection(row)
        results.append(row)

    for row in results:
        row["used_for_motion_fit"] = False
    motion_fit = _fit_motion(results)
    repeat_groups = _repeat_position_groups(results)
    accepted_count = sum(1 for row in results if row.get("status") == "ok")
    rejected_count = sum(1 for row in results if row.get("status") == "rejected")
    error_count = sum(1 for row in results if row.get("status") == "error")
    fit_count = int(motion_fit.get("fit_count", 0)) if motion_fit else 0

    summary = {
        "run_directory": str(directory),
        "metadata_path": str(metadata_path) if metadata_path.exists() else None,
        "available_image_count": int(len(all_image_paths)),
        "image_count": int(len(results)),
        "accepted_count": int(accepted_count),
        "rejected_count": int(rejected_count),
        "error_count": int(error_count),
        "manual_rejected_count": int(sum(1 for row in results if row.get("error") == "manual_rejected")),
        "motion_fit_count": int(fit_count),
        "repeat_position_group_count": int(len(repeat_groups)),
        "options": _options_payload(opts),
    }
    payload = {
        "schema_version": 1,
        "status": "ok" if accepted_count else "error",
        "summary": summary,
        "motion_fit": motion_fit or {"status": "error", "error": "not_enough_eligible_frames", "fit_count": fit_count},
        "repeat_position_groups": repeat_groups,
        "results": results,
    }
    payload["motion_quality"] = summarize_motion_fit_quality(payload)
    return payload


def _options_payload(options: ScaleBarMotionOptions) -> dict[str, Any]:
    return {field: getattr(options, field) for field in options.__dataclass_fields__}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "filename",
        "status",
        "quality_flags",
        "warning_flags",
        "center_x",
        "center_y",
        "center_x_source",
        "center_y_source",
        "spine_rect_x",
        "spine_bbox_x",
        "spine_centroid_x",
        "spine_x_disagreement_px",
        "x_profile_center_bounds",
        "x_profile_center_centroid",
        "x_profile_left_x",
        "x_profile_right_x",
        "x_profile_width_px",
        "x_profile_disagreement_px",
        "y_profile_center_bounds",
        "y_profile_center_centroid",
        "y_profile_top_y",
        "y_profile_bottom_y",
        "y_profile_height_px",
        "y_profile_disagreement_px",
        "spine_long_px",
        "spine_angle_from_vertical_deg",
        "main_peak_count",
        "tick_peak_count",
        "tick_spacing_median_px",
        "tick_spacing_cv_pct",
        "X_position",
        "Y_position",
        "Z_position",
        "commands_idle_at_frame",
        "capture_context",
        "used_for_motion_fit",
        "predicted_center_x",
        "predicted_center_y",
        "residual_x_px",
        "residual_y_px",
        "residual_norm_px",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flat = {field: row.get(field) for field in fields}
            flat["quality_flags"] = ";".join(row.get("quality_flags") or [])
            flat["warning_flags"] = ";".join(row.get("warning_flags") or [])
            writer.writerow(flat)


def _result_by_filename(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("filename")): row for row in payload.get("results", [])}


def _select_debug_filenames(payload: dict[str, Any], *, debug_all: bool = False, debug_limit: int = 10) -> list[str]:
    rows = list(payload.get("results", []))
    if debug_all:
        return [str(row["filename"]) for row in rows]

    selected: list[str] = []
    limit = max(1, int(debug_limit))

    def add(filename: str | None) -> None:
        if filename and filename not in selected and len(selected) < limit:
            selected.append(filename)

    for row in sorted(rows, key=lambda item: float(item.get("residual_norm_px") or -1), reverse=True)[:3]:
        if row.get("residual_norm_px") is not None:
            add(str(row.get("filename")))

    for group in payload.get("repeat_position_groups", [])[:3]:
        for filename in list(group.get("filenames", []))[:2]:
            add(str(filename))

    rejected = [row for row in rows if row.get("status") != "ok"]
    for row in rejected[:2]:
        add(str(row.get("filename")))

    controls = [
        row
        for row in rows
        if row.get("status") == "ok" and row.get("residual_norm_px") is not None and row.get("filename")
    ]
    controls = sorted(controls, key=lambda item: float(item.get("residual_norm_px") or 0.0))
    if controls:
        for fraction in (0.1, 0.3, 0.5, 0.7, 0.9):
            add(str(controls[min(len(controls) - 1, int(round((len(controls) - 1) * fraction)))].get("filename")))

    if not selected:
        for row in rows[:limit]:
            add(str(row.get("filename")))
    return selected


def _draw_raw_overlay(ax, rgb: np.ndarray, result: dict[str, Any], debug: dict[str, Any], title: str) -> None:
    ax.imshow(rgb)
    ax.set_title(title, fontsize=9)
    ax.axis("off")
    spine = debug.get("spine")
    if spine is not None:
        box = np.asarray(spine["rect_box"], dtype=float)
        box = np.vstack([box, box[0]])
        ax.plot(box[:, 0], box[:, 1], color="lime", linewidth=1.5)
        contour = spine["contour"].squeeze(axis=1)
        if contour.ndim == 2 and len(contour) > 2:
            ax.plot(contour[:, 0], contour[:, 1], color="yellow", linewidth=0.8)
    if result.get("center_x") is not None and result.get("center_y") is not None:
        ax.plot(float(result["center_x"]), float(result["center_y"]), marker="+", markersize=14, markeredgewidth=2.2, color="red")
    if result.get("roi_x0") is not None and result.get("roi_x1") is not None:
        ax.axvline(int(result["roi_x0"]), color="cyan", linewidth=0.8)
        ax.axvline(int(result["roi_x1"]), color="cyan", linewidth=0.8)
    if result.get("x_profile_left_x") is not None and result.get("x_profile_right_x") is not None:
        ax.axvline(int(result["x_profile_left_x"]), color="orange", linewidth=1.1)
        ax.axvline(int(result["x_profile_right_x"]), color="orange", linewidth=1.1)
    if result.get("y_profile_top_y") is not None and result.get("y_profile_bottom_y") is not None:
        ax.axhline(int(result["y_profile_top_y"]), color="red", linestyle=":", linewidth=1.0)
        ax.axhline(int(result["y_profile_bottom_y"]), color="red", linestyle=":", linewidth=1.0)


def _save_debug_panel(
    image_path: Path,
    result: dict[str, Any],
    options: ScaleBarMotionOptions,
    output_dir: Path,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _fresh_result, debug = _analyze_image_internal(
        image_path,
        metadata={field: result.get(field) for field in METADATA_FIELDS},
        options=options,
        include_debug=True,
    )
    result = {**result, **{key: value for key, value in _fresh_result.items() if key not in METADATA_FIELDS}}
    ticks = debug.get("ticks") or {}
    spine = debug.get("spine") or {}

    fig, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
    axes = axes.ravel()
    _draw_raw_overlay(axes[0], debug["rgb"], result, debug, "raw + spine/ROI/final center")
    axes[1].imshow(spine.get("dark_mask", np.zeros_like(debug["gray"])), cmap="gray")
    axes[1].set_title(f"dark mask @ threshold {spine.get('threshold', 'n/a')}", fontsize=9)
    axes[1].axis("off")
    axes[2].imshow(spine.get("eroded_mask", np.zeros_like(debug["gray"])), cmap="gray")
    axes[2].set_title("eroded spine mask", fontsize=9)
    axes[2].axis("off")

    roi_mask = ticks.get("local_contrast_roi_mask")
    if roi_mask is not None:
        axes[3].imshow(roi_mask, cmap="gray")
    else:
        axes[3].imshow(np.zeros_like(debug["gray"]), cmap="gray")
    axes[3].set_title("local-contrast ROI mask", fontsize=9)
    axes[3].axis("off")

    signal = ticks.get("tick_signal")
    if signal is not None:
        axes[4].plot(np.arange(len(signal)), signal, color="0.75", linewidth=0.7, label="raw")
        y_profile = ticks.get("y_profile") or {}
        y_signal = y_profile.get("smooth_signal") if y_profile else None
        if y_signal is not None:
            axes[4].plot(np.arange(len(y_signal)), y_signal, color="black", linewidth=1, label="smooth")
            axes[4].axhline(float(y_profile["threshold"]), color="tab:blue", linestyle="--", linewidth=0.8)
            axes[4].axvline(float(y_profile["left"]), color="orange", linestyle="--", linewidth=1.0)
            axes[4].axvline(float(y_profile["right"]), color="orange", linestyle="--", linewidth=1.0)
            axes[4].axvline(float(y_profile["center_bounds"]), color="red", linewidth=1.3, label="bounds center")
            axes[4].axvline(float(y_profile["center_centroid"]), color="tab:purple", linewidth=1.0, label="centroid")
        peaks = np.asarray(ticks.get("tick_peaks", []), dtype=int)
        accepted = np.asarray(ticks.get("accepted_tick_peaks", []), dtype=int)
        if peaks.size:
            axes[4].scatter(peaks, signal[peaks], s=14, color="tab:blue", label="all peaks")
        if accepted.size:
            axes[4].scatter(accepted, signal[accepted], s=22, color="red", label="accepted")
        axes[4].legend(loc="upper right", fontsize=7)
    axes[4].set_title("scale-bar row-sum profile", fontsize=9)
    axes[4].set_xlabel("image y pixel")
    axes[4].set_ylabel("mask pixels in ROI")

    x_profile = ticks.get("x_profile") or {}
    x_signal = x_profile.get("smooth_signal") if x_profile else None
    if x_signal is not None:
        x0 = int(ticks.get("roi_x0", 0))
        x_coords = np.arange(len(x_signal)) + x0
        axes[5].plot(x_coords, x_signal, color="black", linewidth=1)
        axes[5].axhline(float(x_profile["threshold"]), color="tab:blue", linestyle="--", linewidth=0.8)
        axes[5].axvline(float(x_profile["left"]), color="orange", linestyle="--", linewidth=1.0)
        axes[5].axvline(float(x_profile["right"]), color="orange", linestyle="--", linewidth=1.0)
        axes[5].axvline(float(x_profile["center_bounds"]), color="red", linewidth=1.3, label="bounds center")
        axes[5].axvline(float(x_profile["center_centroid"]), color="tab:purple", linewidth=1.0, label="centroid")
        axes[5].legend(loc="upper right", fontsize=7)
    axes[5].set_title("scale-bar column-sum profile", fontsize=9)
    axes[5].set_xlabel("image x pixel")
    axes[5].set_ylabel("dark-mask pixels in tick bounds")

    title = f"{result.get('filename')} | {result.get('status')}"
    if result.get("quality_flags"):
        title += " | " + ", ".join(result.get("quality_flags") or [])
    if result.get("warning_flags"):
        title += " | warnings: " + ", ".join(result.get("warning_flags") or [])
    spine_long = _finite_float(result.get("spine_long_px"))
    spine_long_text = "n/a" if spine_long is None else f"{spine_long:.1f}"
    title += (
        f"\ncenter=({result.get('center_x')}, {result.get('center_y')}) "
        f"peaks={result.get('main_peak_count')} "
        f"spine_long={spine_long_text} "
        f"x_width={result.get('x_profile_width_px')} "
        f"y_height={result.get('y_profile_height_px')}"
    )
    fig.suptitle(title, fontsize=11)
    output_path = output_dir / f"debug_{Path(str(result.get('filename'))).stem}.png"
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _save_contact_sheet(
    payload: dict[str, Any],
    filenames: list[str],
    output_dir: Path,
    options: ScaleBarMotionOptions,
    name: str,
    title: str,
) -> Path | None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_filename = _result_by_filename(payload)
    rows = [by_filename[filename] for filename in filenames if filename in by_filename]
    if not rows:
        return None
    n = len(rows)
    fig, axes = plt.subplots(1, n, figsize=(4.6 * n, 4.6), constrained_layout=True)
    if n == 1:
        axes = [axes]
    for ax, row in zip(axes, rows):
        image_path = Path(row["path"])
        _fresh, debug = _analyze_image_internal(image_path, options=options, include_debug=True)
        _draw_raw_overlay(
            ax,
            debug["rgb"],
            row,
            debug,
            f"{row['filename']}\nc=({row.get('center_x', 0):.1f},{row.get('center_y', 0):.1f})\nres={row.get('residual_norm_px', '')}",
        )
    fig.suptitle(title, fontsize=12)
    output_path = output_dir / name
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def _fit_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in payload.get("results", [])
        if row.get("used_for_motion_fit")
        and _finite_float(row.get("center_x")) is not None
        and _finite_float(row.get("center_y")) is not None
        and _finite_float(row.get("predicted_center_x")) is not None
        and _finite_float(row.get("predicted_center_y")) is not None
        and _finite_float(row.get("residual_x_px")) is not None
        and _finite_float(row.get("residual_y_px")) is not None
        and _finite_float(row.get("residual_norm_px")) is not None
    ]


def _axis_limits_with_margin(values: np.ndarray) -> tuple[float, float]:
    values = values[np.isfinite(values)]
    if values.size == 0:
        return (0.0, 1.0)
    low = float(np.min(values))
    high = float(np.max(values))
    if math.isclose(low, high):
        return (low - 1.0, high + 1.0)
    margin = (high - low) * 0.06
    return (low - margin, high + margin)


def _save_fit_summary_plots(payload: dict[str, Any], output_dir: Path) -> list[Path]:
    rows = _fit_rows(payload)
    if len(rows) < 3:
        return []

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    filenames = [str(row.get("filename", "")) for row in rows]
    frame_numbers = np.arange(1, len(rows) + 1, dtype=float)
    observed_x = np.asarray([float(row["center_x"]) for row in rows], dtype=float)
    observed_y = np.asarray([float(row["center_y"]) for row in rows], dtype=float)
    predicted_x = np.asarray([float(row["predicted_center_x"]) for row in rows], dtype=float)
    predicted_y = np.asarray([float(row["predicted_center_y"]) for row in rows], dtype=float)
    residual_x = np.asarray([float(row["residual_x_px"]) for row in rows], dtype=float)
    residual_y = np.asarray([float(row["residual_y_px"]) for row in rows], dtype=float)
    residual_norm = np.asarray([float(row["residual_norm_px"]) for row in rows], dtype=float)
    fit = payload.get("motion_fit") or {}

    written = []
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), constrained_layout=True)
    axes = axes.ravel()
    for ax, observed, predicted, label, rmse_key in (
        (axes[0], observed_x, predicted_x, "center x", "rmse_x_px"),
        (axes[1], observed_y, predicted_y, "center y", "rmse_y_px"),
    ):
        low, high = _axis_limits_with_margin(np.concatenate([observed, predicted]))
        ax.scatter(predicted, observed, s=26, alpha=0.8)
        ax.plot([low, high], [low, high], color="black", linestyle="--", linewidth=1)
        ax.set_xlim(low, high)
        ax.set_ylim(low, high)
        ax.set_xlabel(f"predicted {label} (px)")
        ax.set_ylabel(f"observed {label} (px)")
        rmse = _finite_float(fit.get(rmse_key))
        if rmse is not None:
            ax.set_title(f"{label}: RMSE {rmse:.2f} px")
        else:
            ax.set_title(label)

    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].plot(frame_numbers, residual_x, marker="o", markersize=3, linewidth=1, label="x residual")
    axes[2].plot(frame_numbers, residual_y, marker="o", markersize=3, linewidth=1, label="y residual")
    axes[2].set_xlabel("fit frame order")
    axes[2].set_ylabel("observed - predicted (px)")
    axes[2].set_title("Residuals Across Accepted Frames")
    axes[2].legend(fontsize=8)

    axes[3].hist(residual_norm, bins=min(20, max(5, int(round(math.sqrt(len(residual_norm)))))), color="0.35")
    median_res = _finite_float(fit.get("median_2d_residual_px"))
    p95_res = _finite_float(fit.get("p95_2d_residual_px"))
    if median_res is not None:
        axes[3].axvline(median_res, color="tab:green", linewidth=1.2, label=f"median {median_res:.1f}")
    if p95_res is not None:
        axes[3].axvline(p95_res, color="tab:red", linewidth=1.2, label=f"p95 {p95_res:.1f}")
    axes[3].set_xlabel("2D residual (px)")
    axes[3].set_ylabel("frame count")
    axes[3].set_title("Residual Norm Distribution")
    axes[3].legend(fontsize=8)
    fig.suptitle("Scale-Bar Motion Fit Summary", fontsize=13)
    path = output_dir / "summary_fit_observed_predicted_residuals.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    fig, ax = plt.subplots(figsize=(8, 7), constrained_layout=True)
    scatter = ax.scatter(observed_x, observed_y, c=residual_norm, cmap="viridis", s=36, zorder=3)
    ax.quiver(
        predicted_x,
        predicted_y,
        residual_x,
        residual_y,
        angles="xy",
        scale_units="xy",
        scale=1,
        color="tab:red",
        alpha=0.65,
        width=0.003,
        zorder=2,
    )
    worst_indices = np.argsort(residual_norm)[-min(8, len(rows)) :]
    for idx in worst_indices:
        ax.annotate(Path(filenames[idx]).stem.replace("scale_bar_", ""), (observed_x[idx], observed_y[idx]), fontsize=7)
    ax.set_xlabel("image x center (px)")
    ax.set_ylabel("image y center (px)")
    ax.set_title("Image-Space Residual Vectors (predicted to observed)")
    ax.invert_yaxis()
    ax.grid(True, alpha=0.25)
    fig.colorbar(scatter, ax=ax, label="2D residual (px)")
    path = output_dir / "summary_fit_residual_vectors.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    groups = payload.get("repeat_position_groups", [])
    if groups:
        labels = [f"{group.get('X_position')}/{group.get('Z_position')}" for group in groups]
        x_ranges = np.asarray([float(group.get("x_range_px", 0.0)) for group in groups], dtype=float)
        y_ranges = np.asarray([float(group.get("y_range_px", 0.0)) for group in groups], dtype=float)
        indices = np.arange(len(groups))
        fig, ax = plt.subplots(figsize=(max(8, len(groups) * 0.45), 5), constrained_layout=True)
        width = 0.4
        ax.bar(indices - width / 2, x_ranges, width=width, label="x range")
        ax.bar(indices + width / 2, y_ranges, width=width, label="y range")
        ax.set_xticks(indices)
        ax.set_xticklabels(labels, rotation=70, ha="right", fontsize=7)
        ax.set_ylabel("repeat-position center range (px)")
        ax.set_title("Repeat-Position Scatter by Machine X/Z")
        ax.legend()
        path = output_dir / "summary_repeat_position_ranges.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(path)

    return written


def write_debug_outputs(
    result: dict[str, Any],
    output_dir: str | Path,
    *,
    options: ScaleBarMotionOptions | dict[str, Any] | None = None,
    debug_all: bool = False,
    debug_limit: int = 10,
    contact_limit: int = 3,
    summary_only: bool = False,
) -> dict[str, Any]:
    """Generate diagnostic image panels and an HTML index for a result payload."""
    opts = ScaleBarMotionOptions.from_value(options or result.get("summary", {}).get("options"))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if "results" not in result:
        result = {
            "schema_version": 1,
            "status": result.get("status", "error"),
            "summary": {"image_count": 1, "accepted_count": int(result.get("status") == "ok")},
            "motion_fit": None,
            "repeat_position_groups": [],
            "results": [result],
        }

    selected = [] if summary_only else _select_debug_filenames(result, debug_all=debug_all, debug_limit=debug_limit)
    by_filename = _result_by_filename(result)
    written = []
    written.extend(_save_fit_summary_plots(result, output))
    for filename in selected:
        row = by_filename.get(filename)
        if not row:
            continue
        written.append(_save_debug_panel(Path(row["path"]), row, opts, output))

    contact_groups = [] if summary_only else result.get("repeat_position_groups", [])[: max(0, int(contact_limit))]
    for idx, group in enumerate(contact_groups, start=1):
        contact = _save_contact_sheet(
            result,
            list(group.get("filenames", [])),
            output,
            opts,
            f"contact_repeat_group_{idx:02d}_X{group.get('X_position')}_Z{group.get('Z_position')}.png",
            f"Repeat group {idx}: X/Z=({group.get('X_position')}, {group.get('Z_position')}), "
            f"x_std={float(group.get('x_std_px', 0.0)):.1f}px",
        )
        if contact:
            written.append(contact)

    summary = {
        "output_dir": str(output),
        "debug_all": bool(debug_all),
        "debug_limit": int(debug_limit),
        "contact_limit": int(contact_limit),
        "summary_only": bool(summary_only),
        "selected_debug_files": selected,
        "written_files": [str(path) for path in written],
    }
    (output / "debug_summary.json").write_text(json.dumps(summary, indent=2, default=_json_default) + "\n", encoding="utf-8")
    _write_debug_index(output, result, written)
    return summary


def _write_debug_index(output_dir: Path, payload: dict[str, Any], written: list[Path]) -> None:
    image_names = [path.name for path in written if path.suffix.lower() == ".png"]
    summaries = [name for name in image_names if name.startswith("summary_")]
    contact = [name for name in image_names if name.startswith("contact_")]
    panels = [name for name in image_names if name.startswith("debug_")]
    parts = [
        "<!doctype html><meta charset=\"utf-8\"><title>Scale Bar Motion Center Debug</title>",
        "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;line-height:1.35}"
        "img{max-width:100%;height:auto;border:1px solid #ddd}.grid{display:grid;"
        "grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px}.card{padding:12px;"
        "border:1px solid #ddd;border-radius:6px}.muted{color:#555}</style>",
        "<h1>Scale Bar Motion Center Debug</h1>",
        f"<p class=\"muted\">Images: {payload.get('summary', {}).get('image_count')} | "
        f"accepted: {payload.get('summary', {}).get('accepted_count')} | "
        f"fit count: {payload.get('summary', {}).get('motion_fit_count')}</p>",
    ]
    if summaries:
        parts.append("<h2>Summary fit plots</h2><div class=\"grid\">")
        for name in summaries:
            escaped = html.escape(name)
            parts.append(f"<div class=\"card\"><h3>{escaped}</h3><a href=\"{escaped}\"><img src=\"{escaped}\"></a></div>")
        parts.append("</div>")
    if contact:
        parts.append("<h2>Repeat-position contact sheets</h2><div class=\"grid\">")
        for name in contact:
            escaped = html.escape(name)
            parts.append(f"<div class=\"card\"><h3>{escaped}</h3><a href=\"{escaped}\"><img src=\"{escaped}\"></a></div>")
        parts.append("</div>")
    parts.append("<h2>Per-image pipeline panels</h2><div class=\"grid\">")
    for name in panels:
        escaped = html.escape(name)
        parts.append(f"<div class=\"card\"><h3>{escaped}</h3><a href=\"{escaped}\"><img src=\"{escaped}\"></a></div>")
    parts.append("</div>")
    parts.append("<h2>Data</h2><ul><li><a href=\"debug_summary.json\">debug_summary.json</a></li></ul>")
    (output_dir / "index.html").write_text("\n".join(parts), encoding="utf-8")


def _output_path_for(input_path: Path, output_arg: str) -> Path:
    if output_arg:
        return Path(output_arg)
    if input_path.is_dir():
        return input_path / "scale_bar_motion_analysis.json"
    return input_path.with_name(f"{input_path.stem}_motion_analysis.json")


def _csv_path_for(input_path: Path, csv_arg: str) -> Path | None:
    if csv_arg:
        return Path(csv_arg)
    if input_path.is_dir():
        return input_path / "scale_bar_motion_centers.csv"
    return None


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze scale-bar center motion against machine X/Z metadata.")
    parser.add_argument("path", help="Image file or capture directory containing scale-bar images.")
    parser.add_argument("--metadata", default="metadata.jsonl", help="Metadata JSONL filename for directory mode.")
    parser.add_argument("--output", default="", help="JSON output path.")
    parser.add_argument("--csv", default="", help="CSV output path for directory mode.")
    parser.add_argument("--debug", action="store_true", help="Generate diagnostic plots and HTML index.")
    parser.add_argument("--debug-dir", default="debug_center_extraction", help="Debug output directory.")
    parser.add_argument("--debug-all", action="store_true", help="Render every frame instead of selected debug examples.")
    parser.add_argument("--debug-limit", type=int, default=10, help="Number of per-image debug panels to render.")
    parser.add_argument("--debug-contact-limit", type=int, default=3, help="Number of repeat-position contact sheets to render.")
    parser.add_argument("--debug-summary-only", action="store_true", help="Write only summary fit plots and the HTML index.")
    parser.add_argument("--image-limit", type=int, default=0, help="Evenly sample at most this many images in directory mode.")
    parser.add_argument("--min-main-peaks", type=int, default=80, help="Minimum accepted tick peaks for an accepted frame.")
    parser.add_argument("--min-spine-long", type=float, default=580.0, help="Minimum eroded spine long side in pixels.")
    parser.add_argument("--min-y-profile-height", type=float, default=580.0, help="Minimum row-profile support height in pixels.")
    parser.add_argument("--max-spacing-cv-pct", type=float, default=20.0, help="Maximum accepted tick spacing CV percent.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    input_path = Path(args.path)
    options = replace(
        ScaleBarMotionOptions(),
        min_main_peaks=int(args.min_main_peaks),
        min_spine_long=float(args.min_spine_long),
        min_y_profile_height_px=float(args.min_y_profile_height),
        max_spacing_cv_pct=float(args.max_spacing_cv_pct),
    )

    if input_path.is_dir():
        image_limit = int(args.image_limit) if int(args.image_limit) > 0 else None
        payload = analyze_scale_bar_motion_directory(
            input_path,
            options=options,
            metadata_filename=args.metadata,
            image_limit=image_limit,
        )
    else:
        payload = analyze_scale_bar_center_image(input_path, options=options)

    output_path = _output_path_for(input_path, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n", encoding="utf-8")

    if input_path.is_dir():
        csv_path = _csv_path_for(input_path, args.csv)
        if csv_path is not None:
            _write_csv(csv_path, payload.get("results", []))

    if args.debug:
        debug_dir = Path(args.debug_dir)
        if not debug_dir.is_absolute():
            debug_dir = input_path / debug_dir if input_path.is_dir() else input_path.parent / debug_dir
        write_debug_outputs(
            payload,
            debug_dir,
            options=options,
            debug_all=bool(args.debug_all),
            debug_limit=int(args.debug_limit),
            contact_limit=int(args.debug_contact_limit),
            summary_only=bool(args.debug_summary_only),
        )

    print(json.dumps(payload, indent=2, default=_json_default))
    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
