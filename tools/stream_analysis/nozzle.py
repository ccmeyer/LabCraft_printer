from __future__ import annotations

from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np

from tools.stream_analysis.dataset import (
    _clean_text,
    _int_or_none,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
)


NOZZLE_STAGE_DIRNAME = "stage_02_nozzle"

ATTACHED_MODES = {
    "attached_black_droplet_center",
    "attached_core_separation",
    "visible_nozzle_line",
}
DETACHED_MODES = {"only_nozzle"}
STABLE_SHIFT_MODES = {"attached_core_separation", "visible_nozzle_line", "only_nozzle"}
CANDIDATE_ORDER = [
    "attached_black_droplet_center",
    "attached_core_separation",
    "visible_nozzle_line",
    "only_nozzle",
]

MODE_SCORE_THRESHOLDS = {
    "only_nozzle": 0.56,
    "attached_support_low": 0.38,
    "droplet": 0.60,
    "visible_line_enter": 0.42,
    "visible_line_keep": 0.28,
    "visible_line_strong_override": 0.55,
    "core": 0.32,
    "override_margin": 0.12,
}

TRACK_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "image_relpath",
    "image_exists",
    "captured_at_utc",
    "flash_delay_us",
    "delay_from_emergence_us",
    "search_x0",
    "search_y0",
    "search_x1",
    "search_y1",
    "search_width",
    "search_height",
    "raw_nozzle_x_px",
    "raw_nozzle_y_px",
    "tracked_nozzle_x_px",
    "tracked_nozzle_y_px",
    "raw_confidence",
    "tracked_confidence",
    "detection_mode",
    "raw_mode",
    "final_mode",
    "filled_from_segment",
    "used_segment_fill",
    "segment_id",
    "shift_event_before",
    "static_line_x_px",
    "static_line_y_px",
    "attached_component_centroid_x_px",
    "attached_component_centroid_y_px",
    "attached_component_area_px",
    "compact_droplet_score",
    "neck_y_px",
    "neck_width_px",
    "neck_score",
    "contour_completeness_score",
    "contour_bilateral_row_fraction",
    "contour_width_median_px",
    "contour_width_iqr_px",
    "contour_clipped_warning",
    "stable_visible_line_y_px",
    "pending_visible_line_y_px",
    "provisional_visible_line_y_px",
    "provisional_visible_line_count",
    "visible_line_search_center_y_px",
    "visible_line_search_radius_px",
    "visible_line_acquisition_search_center_y_px",
    "visible_line_acquisition_upper_bound_y_px",
    "line_band_y_px",
    "line_band_score",
    "late_widening_y_px",
    "late_widening_score",
    "late_widening_used",
    "visible_line_band_top_y_px",
    "visible_line_band_bottom_y_px",
    "visible_line_band_height_px",
    "visible_line_span_width_px",
    "visible_line_span_fraction",
    "visible_line_dark_delta",
    "visible_line_vertical_overlap",
    "visible_line_used_hysteresis",
    "visible_line_used_relaxed_fallback",
    "visible_line_used_plateau_only_fallback",
    "visible_line_valid_late_band",
    "visible_line_plateau_mode",
    "plateau_suppressed_on_acquisition",
    "hollow_bulb_guard_active",
    "visible_line_rejected_by_hollow_bulb_guard",
    "visible_line_rejected_by_upper_cue_conflict",
    "visible_line_lower_peak_prior_constrained",
    "visible_line_effective_lower_peak_y_px",
    "bridge_suppressed_by_clipped_contour",
    "bridge_suppressed_by_plateau",
    "bridge_suppressed_by_prior_conflict",
    "late_bridge_delta_from_prior_px",
    "late_plateau_delta_from_prior_px",
    "visible_line_bridge_x0_px",
    "visible_line_bridge_x1_px",
    "late_plateau_band_top_y_px",
    "late_plateau_band_bottom_y_px",
    "late_plateau_picked_y_px",
    "only_nozzle_y_px",
    "only_nozzle_score",
    "only_nozzle_roi_centers_y_px",
    "only_nozzle_selected_roi_center_y_px",
    "only_nozzle_candidate_source",
    "only_nozzle_prior_band_used",
    "only_nozzle_prior_band_candidate_count",
    "only_nozzle_rejected_far_from_prior",
    "only_nozzle_transition_scoring_used",
    "only_nozzle_distance_from_stable_prior_px",
    "only_nozzle_rejected_lower_reflection",
    "only_nozzle_anchor_rejected_as_low_reflection",
    "droplet_suppressed_as_reflection",
    "attached_support_score",
    "bright_core_upper_y_px",
    "bright_core_lower_y_px",
    "separation_band_y_px",
    "profile_valley_score",
    "candidate_component_count",
    "top_candidate_count",
    "candidate_mask_area_px",
    "candidate_band_width_px",
    "candidate_top_y_px",
    "candidate_bottom_y_px",
    "transition_fill_used",
    "transition_fill_source",
    "anchor_rejected_as_reflection",
    "sample_frame",
]


def _normalize_range(value: float | None, low: float, high: float):
    if value is None:
        return 0.0
    if high <= low:
        return 0.0
    return float(max(0.0, min(1.0, (float(value) - float(low)) / float(high - low))))


def _serialize_float_list(values: list[float] | tuple[float, ...] | None, *, digits: int = 1):
    if not values:
        return None
    cleaned = []
    for value in values:
        if value is None:
            continue
        cleaned.append(float(value))
    if not cleaned:
        return None
    return "|".join(f"{value:.{digits}f}" for value in cleaned)


def _load_gray_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not load grayscale image: {path}")
    return image


def _search_bounds(
    image_shape,
    *,
    search_width_frac: float,
    search_top_frac: float,
    search_bottom_frac: float,
):
    height, width = image_shape[:2]
    half_width = int(round(width * search_width_frac / 2.0))
    center_x = width // 2
    x0 = max(0, center_x - half_width)
    x1 = min(width, center_x + half_width)
    y0 = max(0, min(height - 1, int(round(height * search_top_frac))))
    y1 = max(y0 + 1, min(height, int(round(height * search_bottom_frac))))
    return {
        "x0": int(x0),
        "y0": int(y0),
        "x1": int(x1),
        "y1": int(y1),
        "width": int(x1 - x0),
        "height": int(y1 - y0),
    }


def _sample_indices(frame_count: int, *, sample_count: int, extra_frame_indices: list[int] | None = None):
    indices = set()
    if frame_count <= 0:
        return []
    if sample_count > 0:
        raw = np.linspace(1, frame_count, num=sample_count)
        indices.update(int(round(float(value))) for value in raw)
    for value in extra_frame_indices or []:
        if 1 <= int(value) <= frame_count:
            indices.add(int(value))
    return sorted(indices)


def _local_contrast_residual(search_gray: np.ndarray, *, blur_sigma: float):
    search_float = search_gray.astype(np.float32)
    blurred = cv2.GaussianBlur(search_float, (0, 0), blur_sigma)
    return np.clip(blurred - search_float, 0.0, None)


def _filter_components_by_area(mask: np.ndarray, *, min_area_px: int):
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    filtered = np.zeros_like(mask, dtype=np.uint8)
    for label in range(1, int(count)):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < int(min_area_px):
            continue
        filtered[labels == int(label)] = 255
    return filtered


def _connected_weak_mask_v2(weak_mask: np.ndarray, strong_mask: np.ndarray, *, min_area_px: int):
    dilated_strong = cv2.dilate(strong_mask, np.ones((7, 7), np.uint8), iterations=1)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(weak_mask, connectivity=8)
    connected = np.zeros_like(weak_mask, dtype=np.uint8)
    for label in range(1, int(count)):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < int(min_area_px):
            continue
        component_mask = labels == int(label)
        if not np.any(dilated_strong[component_mask] > 0):
            continue
        connected[component_mask] = 255
    return connected


def _residual_masks_v2(
    residual: np.ndarray,
    *,
    residual_scale: float,
    residual_threshold: int,
    min_area_px: int,
):
    scaled = np.clip(residual * residual_scale, 0, 255).astype(np.uint8)
    _, strong_mask = cv2.threshold(scaled, int(residual_threshold), 255, cv2.THRESH_BINARY)
    strong_opened = cv2.morphologyEx(strong_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    strong_clean = cv2.morphologyEx(strong_opened, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    weak_threshold = max(8, int(int(residual_threshold) - 8))
    _, weak_mask = cv2.threshold(scaled, int(weak_threshold), 255, cv2.THRESH_BINARY)
    weak_vertical = cv2.morphologyEx(weak_mask, cv2.MORPH_CLOSE, np.ones((3, 1), np.uint8))
    weak_closed = cv2.morphologyEx(weak_vertical, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    weak_connected = _connected_weak_mask_v2(
        weak_closed,
        strong_clean,
        min_area_px=max(8, int(round(float(min_area_px) * 0.18))),
    )
    contour_mask = cv2.bitwise_or(strong_clean, weak_connected)
    contour_mask = cv2.morphologyEx(contour_mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contour_mask = _filter_components_by_area(
        contour_mask,
        min_area_px=max(8, int(round(float(min_area_px) * 0.20))),
    )
    return scaled, strong_clean, contour_mask, weak_closed, weak_connected


def _component_rows(mask: np.ndarray):
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    rows = []
    center_x = float(mask.shape[1]) / 2.0
    for label in range(1, int(count)):
        left = int(stats[label, cv2.CC_STAT_LEFT])
        top = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        centroid_x, centroid_y = centroids[label]
        rows.append(
            {
                "label": int(label),
                "area": int(area),
                "bbox_x": left,
                "bbox_y": top,
                "bbox_w": width,
                "bbox_h": height,
                "bbox_x1": int(left + width),
                "bbox_y1": int(top + height),
                "centroid_x": float(centroid_x),
                "centroid_y": float(centroid_y),
                "center_offset": float(abs(centroid_x - center_x)),
            }
        )
    return rows, labels


def _select_top_candidates(
    components: list[dict],
    *,
    search_width: int,
    min_area_px: int,
    top_band_slack_px: int,
):
    if not components:
        return []

    center_tolerance = max(24.0, float(search_width) * 0.24)
    near_center = [
        row
        for row in components
        if row["area"] >= int(min_area_px) and row["center_offset"] <= center_tolerance
    ]
    candidate_pool = near_center or sorted(
        components,
        key=lambda row: (row["center_offset"], row["bbox_y"], -row["area"]),
    )[:3]
    top_y = min(row["bbox_y"] for row in candidate_pool)
    top_rows = [
        row
        for row in candidate_pool
        if row["bbox_y"] <= (top_y + int(top_band_slack_px))
    ]
    return sorted(top_rows, key=lambda row: (row["bbox_y"], row["center_offset"], -row["area"]))


def _mask_for_label(labels: np.ndarray, label: int | None):
    keep = np.zeros_like(labels, dtype=np.uint8)
    if label is None:
        return keep
    keep[labels == int(label)] = 255
    return keep


def _filled_component_mask(mask: np.ndarray):
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return np.zeros_like(mask, dtype=np.uint8), None
    contour = max(contours, key=cv2.contourArea)
    filled = np.zeros_like(mask, dtype=np.uint8)
    cv2.drawContours(filled, [contour], contourIdx=-1, color=255, thickness=-1)
    return filled, contour


def _augment_candidate_mask_with_local_weak_v2(
    candidate_mask: np.ndarray,
    weak_mask: np.ndarray,
    *,
    stable_visible_line_y_local: float | None,
    previous_attached_y_local: float | None,
):
    target_y_local = stable_visible_line_y_local
    if target_y_local is None:
        target_y_local = previous_attached_y_local
    if target_y_local is None:
        return candidate_mask

    height, width = candidate_mask.shape[:2]
    target_y = int(round(float(target_y_local)))
    y0 = max(0, target_y - 8)
    y1 = min(height, target_y + 9)
    if y1 <= y0:
        return candidate_mask

    ys, xs = np.where(candidate_mask > 0)
    if ys.size <= 0:
        return candidate_mask

    center_x = float(np.mean(xs))
    x_tolerance = max(32.0, float(width) * 0.25)
    dilated_candidate = cv2.dilate(candidate_mask, np.ones((7, 7), np.uint8), iterations=1)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(weak_mask, connectivity=8)
    augmented = candidate_mask.copy()
    for label in range(1, int(count)):
        top = int(stats[label, cv2.CC_STAT_TOP])
        bottom = int(top + stats[label, cv2.CC_STAT_HEIGHT])
        if bottom < y0 or top > y1:
            continue
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 8:
            continue
        centroid_x = float(centroids[label][0])
        if abs(centroid_x - center_x) > x_tolerance:
            continue
        component_mask = labels == int(label)
        if not np.any(dilated_candidate[component_mask] > 0) and not (top <= target_y <= bottom):
            continue
        augmented[component_mask] = 255
    return augmented


def _smooth_profile(values: np.ndarray, sigma: float):
    if values.size <= 1:
        return values.astype(np.float32)
    return cv2.GaussianBlur(values.astype(np.float32).reshape(-1, 1), (1, 0), sigmaX=0.0, sigmaY=sigma).ravel()


def _component_geometry(mask: np.ndarray):
    ys, xs = np.where(mask > 0)
    if ys.size <= 0:
        return None

    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea) if contours else None

    row_records = []
    y0 = int(np.min(ys))
    y1 = int(np.max(ys))
    for y in range(y0, y1 + 1):
        row_x = np.where(mask[y] > 0)[0]
        if row_x.size <= 0:
            continue
        left = int(np.min(row_x))
        right = int(np.max(row_x))
        width = int(right - left + 1)
        centerline = float((left + right) / 2.0)
        row_records.append((int(y), left, right, width, centerline))

    rows = np.array([record[0] for record in row_records], dtype=np.int32)
    lefts = np.array([record[1] for record in row_records], dtype=np.int32)
    rights = np.array([record[2] for record in row_records], dtype=np.int32)
    widths = np.array([record[3] for record in row_records], dtype=np.int32)
    centerlines = np.array([record[4] for record in row_records], dtype=np.float32)
    q90_width = float(np.percentile(widths, 90)) if widths.size else 0.0
    median_width = float(np.median(widths)) if widths.size else 0.0
    max_width = int(np.max(widths)) if widths.size else 0
    perimeter = float(cv2.arcLength(contour, True)) if contour is not None else 0.0
    compactness = 0.0
    if perimeter > 0.0:
        compactness = float(max(0.0, min(1.0, (4.0 * np.pi * float(xs.size)) / (perimeter * perimeter))))

    ellipse_center_x = None
    ellipse_center_y = None
    ellipse_major_axis = None
    ellipse_minor_axis = None
    ellipse_axis_ratio = None
    if contour is not None and len(contour) >= 5:
        (ellipse_center_x, ellipse_center_y), (axis_major, axis_minor), _angle = cv2.fitEllipse(contour)
        ellipse_center_x = float(ellipse_center_x)
        ellipse_center_y = float(ellipse_center_y)
        ellipse_major_axis = float(max(axis_major, axis_minor))
        ellipse_minor_axis = float(min(axis_major, axis_minor))
        ellipse_axis_ratio = float(ellipse_major_axis / max(1e-6, ellipse_minor_axis))

    return {
        "rows": rows,
        "lefts": lefts,
        "rights": rights,
        "widths": widths,
        "centerlines": centerlines,
        "centroid_x": float(np.mean(xs)),
        "centroid_y": float(np.mean(ys)),
        "bbox_x0": int(np.min(xs)),
        "bbox_x1": int(np.max(xs)),
        "bbox_y0": int(np.min(ys)),
        "bbox_y1": int(np.max(ys)),
        "height": int((np.max(ys) - np.min(ys)) + 1),
        "area": int(xs.size),
        "q90_width": q90_width,
        "median_width": median_width,
        "max_width": max_width,
        "perimeter": perimeter,
        "compactness": compactness,
        "contour": contour,
        "ellipse_center_x": ellipse_center_x,
        "ellipse_center_y": ellipse_center_y,
        "ellipse_major_axis": ellipse_major_axis,
        "ellipse_minor_axis": ellipse_minor_axis,
        "ellipse_axis_ratio": ellipse_axis_ratio,
    }


def _row_index_for_local_y(geometry: dict, local_y: int):
    rows = geometry["rows"]
    matches = np.where(rows == int(local_y))[0]
    if matches.size > 0:
        return int(matches[0])
    nearest = int(np.argmin(np.abs(rows.astype(np.int32) - int(local_y))))
    return nearest


def _centerline_x_at_local_y(geometry: dict, local_y: int):
    index = _row_index_for_local_y(geometry, local_y)
    return float(geometry["centerlines"][index])


def _inner_strip_bounds(geometry: dict, index: int, *, margin_frac: float = 0.20):
    left = int(geometry["lefts"][index])
    right = int(geometry["rights"][index])
    width = int(geometry["widths"][index])
    margin = max(1, int(round(width * float(margin_frac))))
    inner_x0 = min(int(right), int(left + margin))
    inner_x1 = max(int(inner_x0 + 1), int(right - margin + 1))
    inner_x1 = min(int(right + 1), inner_x1)
    if inner_x1 <= inner_x0:
        inner_x0 = int(left)
        inner_x1 = int(right + 1)
    return int(inner_x0), int(inner_x1)


def _row_profiles(search_gray: np.ndarray, geometry: dict):
    rows = geometry["rows"]
    lefts = geometry["lefts"]
    rights = geometry["rights"]
    widths = geometry["widths"]
    centerlines = geometry["centerlines"]

    centerline_mean = np.zeros(len(rows), dtype=np.float32)
    inner_mean = np.zeros(len(rows), dtype=np.float32)
    inner_p10 = np.zeros(len(rows), dtype=np.float32)
    inner_p90 = np.zeros(len(rows), dtype=np.float32)

    for index, (local_y, left, right, width, centerline_x) in enumerate(
        zip(rows, lefts, rights, widths, centerlines)
    ):
        cx = int(round(float(centerline_x)))
        strip_x0 = max(0, cx - 3)
        strip_x1 = min(search_gray.shape[1], cx + 4)
        center_strip = search_gray[local_y, strip_x0:strip_x1]
        centerline_mean[index] = float(np.mean(center_strip)) if center_strip.size else 0.0

        inner_x0, inner_x1 = _inner_strip_bounds(geometry, index)
        inner_strip = search_gray[local_y, inner_x0:inner_x1]
        if inner_strip.size:
            inner_mean[index] = float(np.mean(inner_strip))
            inner_p10[index] = float(np.percentile(inner_strip, 10))
            inner_p90[index] = float(np.percentile(inner_strip, 90))

    return {
        "centerline_mean": centerline_mean,
        "centerline_mean_smooth": _smooth_profile(centerline_mean, sigma=1.8),
        "inner_mean": inner_mean,
        "inner_mean_smooth": _smooth_profile(inner_mean, sigma=1.8),
        "inner_p10": inner_p10,
        "inner_p10_smooth": _smooth_profile(inner_p10, sigma=1.8),
        "inner_p90": inner_p90,
        "inner_p90_smooth": _smooth_profile(inner_p90, sigma=1.8),
    }


def _first_broad_index(widths: np.ndarray):
    if widths.size <= 0:
        return None
    q90_width = float(np.percentile(widths, 90))
    if q90_width <= 0:
        return None
    broad_threshold = max(18.0, q90_width * 0.78)
    for index in range(len(widths)):
        window = widths[index : min(len(widths), index + 4)]
        if window.size >= 3 and int(np.count_nonzero(window >= broad_threshold)) >= 3:
            return int(index)
    return None


def _regions_from_mask(mask: np.ndarray):
    indices = np.flatnonzero(mask)
    if indices.size <= 0:
        return []
    regions = []
    start = int(indices[0])
    previous = int(indices[0])
    for value in indices[1:]:
        value = int(value)
        if value == (previous + 1):
            previous = value
            continue
        regions.append((start, previous))
        start = value
        previous = value
    regions.append((start, previous))
    return regions


def _select_bright_regions(geometry: dict, profiles: dict):
    p90 = profiles["inner_p90_smooth"]
    rows = geometry["rows"]
    if p90.size <= 0:
        return [], 0.0

    base_count = max(6, min(len(p90) // 8, 12))
    base_level = float(np.median(p90[:base_count]))
    upper_limit = max(1, int(round(len(p90) * 0.55)))
    threshold = max(base_level + 12.0, float(np.percentile(p90[:upper_limit], 45)))
    if threshold >= float(np.max(p90)):
        threshold = float(base_level + 10.0)

    max_considered_index = max(0, min(len(rows) - 1, int(round(len(rows) * 0.60))))
    bright_mask = p90 >= threshold
    bright_mask[max_considered_index + 1 :] = False
    regions = [region for region in _regions_from_mask(bright_mask) if (region[1] - region[0] + 1) >= 3]
    return regions, float(threshold)


def _peak_index(profile: np.ndarray, region: tuple[int, int]):
    start, end = region
    local = profile[start : end + 1]
    return int(start + int(np.argmax(local)))


def _argmin_between(profile: np.ndarray, start: int, end: int):
    if end < start:
        return None
    local = profile[start : end + 1]
    if local.size <= 0:
        return None
    return int(start + int(np.argmin(local)))


def _candidate_payload(
    mode: str,
    *,
    raw_x_local: float,
    raw_y_local: float,
    confidence: float,
    upper_peak_y_local: float | None = None,
    lower_peak_y_local: float | None = None,
    separation_y_local: float | None = None,
    valley_score: float = 0.0,
):
    return {
        "mode": mode,
        "raw_x_local": float(raw_x_local),
        "raw_y_local": float(raw_y_local),
        "confidence": float(max(0.0, min(1.0, confidence))),
        "upper_peak_y_local": None if upper_peak_y_local is None else float(upper_peak_y_local),
        "lower_peak_y_local": None if lower_peak_y_local is None else float(lower_peak_y_local),
        "separation_y_local": None if separation_y_local is None else float(separation_y_local),
        "valley_score": float(valley_score),
    }


def _detect_only_nozzle_candidate(search_gray: np.ndarray, geometry: dict, profiles: dict):
    height = int(geometry["height"])
    median_width = float(geometry["median_width"])
    if height > 18 or median_width < 16.0:
        return None

    centerline = profiles["centerline_mean_smooth"]
    darkness = float(np.max(centerline) - np.min(centerline))
    row_index = int(np.argmin(centerline))
    local_y = int(geometry["rows"][row_index])
    local_x = float(geometry["centerlines"][row_index])

    thinness_score = max(0.0, 1.0 - ((height - 4.0) / 14.0))
    width_score = min(1.0, median_width / 70.0)
    darkness_score = min(1.0, darkness / 32.0)
    confidence = float(max(0.0, min(1.0, (0.40 * thinness_score) + (0.30 * width_score) + (0.30 * darkness_score))))
    if confidence < 0.30:
        return None

    return _candidate_payload(
        "only_nozzle",
        raw_x_local=local_x,
        raw_y_local=float(local_y),
        confidence=confidence,
        separation_y_local=float(local_y),
        valley_score=float(darkness),
    )


def _attached_split_metrics(geometry: dict, profiles: dict):
    rows = geometry["rows"]
    peak_profile = profiles["inner_p90_smooth"]
    valley_profile = profiles["centerline_mean_smooth"]
    if peak_profile.size < 24 or valley_profile.size != peak_profile.size:
        return None

    lower_start = max(6, int(round(len(rows) * 0.22)))
    lower_peak_index = int(lower_start + int(np.argmax(peak_profile[lower_start:])))
    min_gap_rows = max(18, int(round(len(rows) * 0.12)))
    upper_search_end = int(lower_peak_index - min_gap_rows)
    if upper_search_end < 6:
        return None

    upper_peak_index = int(np.argmax(peak_profile[:upper_search_end]))
    separation_index = _argmin_between(
        valley_profile,
        upper_peak_index + 1,
        lower_peak_index - 1,
    )
    if separation_index is None:
        return None

    upper_peak = float(peak_profile[upper_peak_index])
    lower_peak = float(peak_profile[lower_peak_index])
    valley = float(valley_profile[separation_index])
    upper_delta = float(max(0.0, upper_peak - valley))
    lower_delta = float(max(0.0, lower_peak - valley))
    ridge_depth = float(min(upper_delta, lower_delta))
    separation_local_y = int(rows[separation_index])

    return {
        "upper_peak_index": int(upper_peak_index),
        "lower_peak_index": int(lower_peak_index),
        "separation_index": int(separation_index),
        "upper_peak_y_local": float(rows[upper_peak_index]),
        "lower_peak_y_local": float(rows[lower_peak_index]),
        "separation_y_local": float(separation_local_y),
        "raw_x_local": float(_centerline_x_at_local_y(geometry, separation_local_y)),
        "upper_peak_value": upper_peak,
        "lower_peak_value": lower_peak,
        "valley_value": valley,
        "upper_delta": upper_delta,
        "lower_delta": lower_delta,
        "ridge_depth": ridge_depth,
    }


def _best_local_valley_metrics(geometry: dict, profiles: dict):
    rows = geometry["rows"]
    widths = geometry["widths"]
    center_profile = profiles["centerline_mean_smooth"]
    bright_profile = profiles["inner_p90_smooth"]
    if (
        rows.size < 20
        or center_profile.size != rows.size
        or bright_profile.size != rows.size
    ):
        return None

    start_index = max(8, int(round(rows.size * 0.08)))
    end_index = min(rows.size - 8, int(round(rows.size * 0.72)))
    if end_index <= start_index:
        return None

    q90_width = float(geometry["q90_width"])
    broad_threshold = max(12.0, q90_width * 0.45)
    best = None

    for index in range(start_index, end_index + 1):
        left_index = max(0, index - 14)
        right_index = min(rows.size - 1, index + 14)
        if (index - left_index) < 4 or (right_index - index) < 4:
            continue

        center_value = float(center_profile[index])
        bright_value = float(bright_profile[index])

        upper_center_window = center_profile[left_index:index]
        lower_center_window = center_profile[index + 1 : right_index + 1]
        upper_bright_window = bright_profile[left_index:index]
        lower_bright_window = bright_profile[index + 1 : right_index + 1]
        if (
            upper_center_window.size <= 0
            or lower_center_window.size <= 0
            or upper_bright_window.size <= 0
            or lower_bright_window.size <= 0
        ):
            continue

        upper_center_peak_index = int(left_index + int(np.argmax(upper_center_window)))
        lower_center_peak_index = int(index + 1 + int(np.argmax(lower_center_window)))
        upper_bright_peak_index = int(left_index + int(np.argmax(upper_bright_window)))
        lower_bright_peak_index = int(index + 1 + int(np.argmax(lower_bright_window)))

        upper_center_drop = float(center_profile[upper_center_peak_index] - center_value)
        lower_center_drop = float(center_profile[lower_center_peak_index] - center_value)
        upper_bright_drop = float(bright_profile[upper_bright_peak_index] - bright_value)
        lower_bright_drop = float(bright_profile[lower_bright_peak_index] - bright_value)

        ridge_depth = float(min(upper_center_drop, lower_center_drop))
        bright_depth = float(min(upper_bright_drop, lower_bright_drop))
        width_bonus = float(
            min(22.0, max(0.0, float(widths[index]) - broad_threshold) * 0.60)
        )
        score = float(ridge_depth + (0.35 * bright_depth) + width_bonus)

        candidate = {
            "index": int(index),
            "raw_x_local": float(_centerline_x_at_local_y(geometry, int(rows[index]))),
            "raw_y_local": float(rows[index]),
            "upper_peak_y_local": float(rows[upper_bright_peak_index]),
            "lower_peak_y_local": float(rows[lower_bright_peak_index]),
            "separation_y_local": float(rows[index]),
            "ridge_depth": ridge_depth,
            "bright_depth": bright_depth,
            "width_px": float(widths[index]),
            "score": score,
        }
        if best is None or float(candidate["score"]) > float(best["score"]):
            best = candidate

    return best


def _detect_attached_candidates(search_gray: np.ndarray, geometry: dict, profiles: dict):
    height = int(geometry["height"])
    if height <= 12:
        return {}
    max_width = max(1, int(geometry["max_width"]))
    aspect_ratio = float(height) / float(max_width)
    droplet_like = bool(height <= 110 or aspect_ratio <= 1.35)

    local_y = int(round(float(geometry["centroid_y"])))
    local_x = float(_centerline_x_at_local_y(geometry, local_y))
    centroid_confidence = 0.42 + min(0.28, float(geometry["area"]) / 5000.0)
    if droplet_like:
        centroid_confidence += 0.08
    candidates = {
        "attached_black_droplet_center": _candidate_payload(
            "attached_black_droplet_center",
            raw_x_local=local_x,
            raw_y_local=float(local_y),
            confidence=float(max(0.0, min(1.0, centroid_confidence))),
        )
    }

    split = _attached_split_metrics(geometry, profiles)
    if split is not None:
        upper_delta = float(split["upper_delta"])
        lower_delta = float(split["lower_delta"])
        ridge_depth = float(split["ridge_depth"])
        valley_value = float(split["valley_value"])
        separation_y_local = float(split["separation_y_local"])
        upper_peak_y_local = float(split["upper_peak_y_local"])
        lower_peak_y_local = float(split["lower_peak_y_local"])
        separation_gap_px = float(lower_peak_y_local - separation_y_local)
        upper_gap_px = float(separation_y_local - upper_peak_y_local)

        line_score = (
            (0.55 * ridge_depth)
            + (0.25 * max(0.0, lower_delta - 18.0))
            + (0.20 * max(0.0, 120.0 - valley_value))
        )
        if (
            ridge_depth >= 26.0
            and lower_delta >= 42.0
            and upper_gap_px >= 10.0
            and separation_gap_px >= 10.0
        ):
            line_confidence = min(1.0, 0.46 + (line_score / 160.0))
            candidates["visible_nozzle_line"] = _candidate_payload(
                "visible_nozzle_line",
                raw_x_local=split["raw_x_local"],
                raw_y_local=separation_y_local,
                confidence=line_confidence,
                upper_peak_y_local=upper_peak_y_local,
                lower_peak_y_local=lower_peak_y_local,
                separation_y_local=separation_y_local,
                valley_score=line_score,
            )

        separation_score = (0.45 * upper_delta) + (0.55 * lower_delta)
        if (
            lower_delta >= 24.0
            and upper_gap_px >= 6.0
            and separation_gap_px >= 6.0
        ):
            separation_confidence = min(1.0, 0.38 + (separation_score / 170.0))
            candidates["attached_core_separation"] = _candidate_payload(
                "attached_core_separation",
                raw_x_local=split["raw_x_local"],
                raw_y_local=separation_y_local,
                confidence=separation_confidence,
                upper_peak_y_local=upper_peak_y_local,
                lower_peak_y_local=lower_peak_y_local,
                separation_y_local=separation_y_local,
                valley_score=separation_score,
            )

    local_valley = _best_local_valley_metrics(geometry, profiles)
    if local_valley is not None:
        long_attached = bool(height >= 120)
        local_score = float(local_valley["score"])
        local_confidence = min(1.0, 0.46 + (local_score / 220.0))
        if long_attached and local_score >= 70.0:
            visible_candidate = _candidate_payload(
                "visible_nozzle_line",
                raw_x_local=local_valley["raw_x_local"],
                raw_y_local=local_valley["raw_y_local"],
                confidence=local_confidence,
                upper_peak_y_local=local_valley["upper_peak_y_local"],
                lower_peak_y_local=local_valley["lower_peak_y_local"],
                separation_y_local=local_valley["separation_y_local"],
                valley_score=local_score,
            )
            existing_visible = candidates.get("visible_nozzle_line")
            if existing_visible is None or float(visible_candidate["confidence"]) >= float(
                existing_visible["confidence"]
            ):
                candidates["visible_nozzle_line"] = visible_candidate

    return candidates


def _choose_raw_detection(candidates: dict[str, dict]):
    only_nozzle = candidates.get("only_nozzle")
    visible_line = candidates.get("visible_nozzle_line")
    core = candidates.get("attached_core_separation")
    droplet = candidates.get("attached_black_droplet_center")

    if only_nozzle is not None and float(only_nozzle["confidence"]) >= 0.35:
        attached_best = max(
            [float(candidate["confidence"]) for candidate in [visible_line, core] if candidate is not None],
            default=0.0,
        )
        if attached_best < max(0.48, float(only_nozzle["confidence"]) + 0.05):
            return only_nozzle

    if visible_line is not None and float(visible_line["confidence"]) >= 0.54:
        return visible_line
    if core is not None and float(core["confidence"]) >= 0.44:
        return core
    if only_nozzle is not None and float(only_nozzle["confidence"]) >= 0.30:
        return only_nozzle
    if droplet is not None:
        return droplet
    if core is not None:
        return core
    if visible_line is not None:
        return visible_line
    if only_nozzle is not None:
        return only_nozzle
    return None


def _mode_history_tail(previous_mode_history: tuple[str, ...] | list[str] | None, *, length: int):
    history = list(previous_mode_history or [])
    if len(history) <= int(length):
        return history
    return history[-int(length) :]


def _compact_droplet_metrics_v2(geometry: dict):
    height = int(geometry["height"])
    max_width = max(1, int(geometry["max_width"]))
    aspect_ratio = float(height) / float(max_width)
    compactness = float(geometry.get("compactness") or 0.0)
    ellipse_axis_ratio = geometry.get("ellipse_axis_ratio")
    ellipse_score = 0.55 if ellipse_axis_ratio is None else _normalize_range(2.6 - float(ellipse_axis_ratio), 0.0, 1.8)
    height_score = max(_normalize_range(150.0 - float(height), 0.0, 90.0), 1.0 if height <= 80 else 0.0)
    aspect_score = max(_normalize_range(1.8 - aspect_ratio, 0.0, 0.9), 1.0 if aspect_ratio <= 1.15 else 0.0)
    compact_score = (
        (0.35 * _normalize_range(compactness, 0.20, 0.80))
        + (0.30 * height_score)
        + (0.20 * aspect_score)
        + (0.15 * ellipse_score)
    )
    raw_x_local = (
        float(geometry["ellipse_center_x"])
        if geometry.get("ellipse_center_x") is not None
        else float(geometry["centroid_x"])
    )
    raw_y_local = (
        float(geometry["ellipse_center_y"])
        if geometry.get("ellipse_center_y") is not None
        else float(geometry["centroid_y"])
    )
    return {
        "raw_x_local": raw_x_local,
        "raw_y_local": raw_y_local,
        "score": float(max(0.0, min(1.0, compact_score))),
        "height": height,
        "aspect_ratio": aspect_ratio,
    }


def _first_taper_index_v2(widths: np.ndarray):
    if widths.size <= 0:
        return None
    q90_width = float(np.quantile(widths.astype(np.float32), 0.90))
    taper_threshold = max(8.0, q90_width * 0.62)
    for index in range(1, len(widths)):
        if widths[index] <= taper_threshold and widths[index - 1] > taper_threshold:
            return int(index)
    for index in range(1, len(widths)):
        if widths[index] <= taper_threshold:
            return int(index)
    return None


def _local_band_refine_score_v2(profiles: dict, index: int):
    center = profiles["centerline_mean_smooth"]
    bright = profiles["inner_p90_smooth"]
    dark = profiles["inner_p10_smooth"]
    upper_start = max(0, index - 6)
    upper_end = max(upper_start, index - 1)
    lower_start = min(len(center), index + 1)
    lower_end = min(len(center), index + 7)
    if upper_end <= upper_start or lower_end <= lower_start:
        return None

    upper_center = float(np.mean(center[upper_start:upper_end]))
    lower_center = float(np.mean(center[lower_start:lower_end]))
    upper_bright = float(np.max(bright[upper_start:upper_end]))
    lower_bright = float(np.max(bright[lower_start:lower_end]))
    center_value = float(center[index])
    dark_value = float(dark[index])
    darkness = float(min(upper_center - center_value, lower_center - center_value))
    shoulder_bright = float(min(upper_bright - dark_value, lower_bright - dark_value))
    return {
        "darkness": darkness,
        "shoulder_bright": shoulder_bright,
        "upper_bright_index": int(upper_start + int(np.argmax(bright[upper_start:upper_end]))),
        "lower_bright_index": int(lower_start + int(np.argmax(bright[lower_start:lower_end]))),
    }


def _width_neck_metrics_v2(geometry: dict, profiles: dict):
    rows = geometry["rows"]
    widths = geometry["widths"].astype(np.float32)
    if rows.size < 12:
        return None

    taper_index = _first_taper_index_v2(widths)
    if taper_index is None:
        return None

    q90_width = float(np.quantile(widths, 0.90))
    search_start = max(0, int(taper_index) - 6)
    search_end = min(len(rows) - 1, int(taper_index + max(18, round(len(rows) * 0.24))))

    best_index = int(taper_index)
    best_darkness = -1.0
    best_has_refine = False
    best_upper_bright_index = None
    best_lower_bright_index = None
    for index in range(search_start, search_end + 1):
        metrics = _local_band_refine_score_v2(profiles, index)
        if (
            metrics is None
            or metrics["darkness"] <= 0.5
            or metrics["shoulder_bright"] <= 4.0
        ):
            continue
        width_support = _normalize_range(float(q90_width - widths[index]), max(4.0, q90_width * 0.20), max(8.0, q90_width * 0.75))
        score = float(width_support * 12.0)
        if metrics["darkness"] > 0.0:
            score += float(metrics["darkness"] + (0.25 * metrics["shoulder_bright"]))
        if score > best_darkness:
            best_darkness = score
            best_index = int(index)
            best_has_refine = True
            best_upper_bright_index = int(metrics["upper_bright_index"])
            best_lower_bright_index = int(metrics["lower_bright_index"])

    if not best_has_refine:
        return None

    taper_strength = _normalize_range(float(q90_width - widths[best_index]), max(4.0, q90_width * 0.20), max(8.0, q90_width * 0.75))
    darkness_score = _normalize_range(best_darkness, 6.0, 55.0)
    neck_score = float(max(0.0, min(1.0, (0.55 * taper_strength) + (0.45 * darkness_score))))
    neck_y_local = int(rows[best_index])
    return {
        "index": int(best_index),
        "raw_x_local": float(_centerline_x_at_local_y(geometry, neck_y_local)),
        "raw_y_local": float(neck_y_local),
        "neck_y_local": float(neck_y_local),
        "neck_width_px": float(widths[best_index]),
        "score": neck_score,
        "darkness": float(best_darkness),
        "upper_peak_y_local": None if best_upper_bright_index is None else float(rows[best_upper_bright_index]),
        "lower_peak_y_local": None if best_lower_bright_index is None else float(rows[best_lower_bright_index]),
    }


def _best_dark_run_region_v2(mask: np.ndarray, *, center_offset: int):
    regions = _regions_from_mask(mask)
    if not regions:
        return None
    ordered = sorted(
        regions,
        key=lambda region: (
            0 if region[0] <= int(center_offset) <= region[1] else 1,
            -(region[1] - region[0] + 1),
            region[0],
        ),
    )
    return ordered[0]


def _dark_overlap_fraction_v2(
    search_gray: np.ndarray,
    geometry: dict,
    *,
    neighbor_index: int,
    threshold: float,
    bridge_x0: int,
    bridge_x1: int,
):
    if neighbor_index < 0 or neighbor_index >= len(geometry["rows"]):
        return None
    neighbor_y = int(geometry["rows"][neighbor_index])
    neighbor_x0, neighbor_x1 = _inner_strip_bounds(geometry, neighbor_index, margin_frac=0.12)
    overlap_x0 = max(int(bridge_x0), int(neighbor_x0))
    overlap_x1 = min(int(bridge_x1), int(neighbor_x1 - 1))
    if overlap_x1 < overlap_x0:
        return 0.0
    neighbor_values = search_gray[neighbor_y, overlap_x0 : overlap_x1 + 1].astype(np.float32)
    if neighbor_values.size <= 0:
        return 0.0
    return float(np.count_nonzero(neighbor_values <= float(threshold)) / float(max(1, bridge_x1 - bridge_x0 + 1)))


def _visible_line_row_bridge_metrics_v2(
    search_gray: np.ndarray,
    geometry: dict,
    profiles: dict,
    index: int,
    *,
    stable_visible_line_y_local: float | None = None,
    contour_completeness_score: float | None = None,
):
    metrics = _local_band_refine_score_v2(profiles, index)
    if metrics is None:
        return None

    row_y = int(geometry["rows"][index])
    inner_x0, inner_x1 = _inner_strip_bounds(geometry, index, margin_frac=0.12)
    row_values = search_gray[row_y, inner_x0:inner_x1].astype(np.float32)
    if row_values.size < 6:
        return None

    upper_index = int(metrics["upper_bright_index"])
    lower_index = int(metrics["lower_bright_index"])
    upper_shoulder = float(profiles["inner_p90_smooth"][upper_index])
    lower_shoulder = float(profiles["inner_p90_smooth"][lower_index])
    shoulder_baseline = float(min(upper_shoulder, lower_shoulder))
    provisional_dark = float(np.percentile(row_values, 25))
    provisional_delta = float(max(0.0, shoulder_baseline - provisional_dark))
    if provisional_delta <= 0.0:
        return None

    dark_threshold = float(shoulder_baseline - max(4.0, min(12.0, provisional_delta * 0.55)))
    dark_mask = row_values <= dark_threshold
    center_offset = int(np.clip(int(round(float(geometry["centerlines"][index]) - inner_x0)), 0, max(0, row_values.size - 1)))
    best_region = _best_dark_run_region_v2(dark_mask, center_offset=center_offset)
    if best_region is None:
        return None

    run_start, run_end = best_region
    run_values = row_values[int(run_start) : int(run_end) + 1]
    if run_values.size <= 0:
        return None

    bridge_x0 = int(inner_x0 + run_start)
    bridge_x1 = int(inner_x0 + run_end)
    span_width = int(run_end - run_start + 1)
    span_fraction = float(span_width / float(max(1, row_values.size)))
    centerline_in_run = 1.0 if int(run_start) <= int(center_offset) <= int(run_end) else 0.0

    dark_value = float(np.percentile(run_values, 25))
    dark_delta = float(max(0.0, shoulder_baseline - dark_value))
    upper_support = float(upper_shoulder - dark_value)
    lower_support = float(lower_shoulder - dark_value)
    shoulder_support = float(min(upper_support, lower_support))
    shoulder_valid = bool(upper_support > 0.0 and lower_support > 0.0)
    upper_gap_px = float(row_y - float(geometry["rows"][upper_index]))
    lower_gap_px = float(float(geometry["rows"][lower_index]) - row_y)
    effective_lower_peak_y_local = float(geometry["rows"][lower_index])
    lower_peak_prior_constrained = False
    if (
        stable_visible_line_y_local is not None
        and float(effective_lower_peak_y_local) < float(stable_visible_line_y_local) - 2.0
    ):
        lower_peak_prior_constrained = True
        effective_lower_peak_y_local = float(max(effective_lower_peak_y_local, float(stable_visible_line_y_local) - 2.0))
    late_prior_plausible = not (
        stable_visible_line_y_local is not None
        and float(row_y) < float(stable_visible_line_y_local) - 8.0
        and bool(lower_peak_prior_constrained)
    )

    overlap_values = []
    for neighbor_index in [index - 1, index + 1]:
        overlap = _dark_overlap_fraction_v2(
            search_gray,
            geometry,
            neighbor_index=int(neighbor_index),
            threshold=float(dark_threshold),
            bridge_x0=int(bridge_x0),
            bridge_x1=int(bridge_x1),
        )
        if overlap is not None:
            overlap_values.append(float(overlap))
    vertical_overlap = float(np.mean(overlap_values)) if overlap_values else 0.0

    dark_delta_score = _normalize_range(dark_delta, 5.0, 18.0)
    shoulder_score = _normalize_range(shoulder_support, 5.0, 24.0)
    line_score = float(
        max(
            0.0,
            min(
                1.0,
                (0.35 * span_fraction)
                + (0.20 * centerline_in_run)
                + (0.20 * dark_delta_score)
                + (0.15 * shoulder_score)
                + (0.10 * vertical_overlap),
            ),
        )
    )
    valid_hysteresis_late_band = bool(
        stable_visible_line_y_local is not None
        and float(contour_completeness_score or 0.0) >= 0.85
        and abs(float(row_y) - float(stable_visible_line_y_local)) <= 4.0
        and span_fraction >= 0.30
        and dark_delta >= 5.0
        and shoulder_valid
        and centerline_in_run >= 1.0
        and upper_gap_px >= 2.0
        and lower_gap_px >= 3.0
        and late_prior_plausible
    )

    return {
        "index": int(index),
        "row_y_local": float(row_y),
        "span_width_px": int(span_width),
        "span_fraction": float(span_fraction),
        "centerline_in_run": float(centerline_in_run),
        "dark_delta": float(dark_delta),
        "vertical_overlap": float(vertical_overlap),
        "upper_peak_index": int(upper_index),
        "lower_peak_index": int(lower_index),
        "upper_peak_y_local": float(geometry["rows"][upper_index]),
        "lower_peak_y_local": float(geometry["rows"][lower_index]),
        "dark_threshold": float(dark_threshold),
        "shoulder_valid": bool(shoulder_valid),
        "upper_gap_px": float(upper_gap_px),
        "lower_gap_px": float(lower_gap_px),
        "effective_lower_peak_y_local": float(effective_lower_peak_y_local),
        "lower_peak_prior_constrained": bool(lower_peak_prior_constrained),
        "late_prior_plausible": bool(late_prior_plausible),
        "bridge_x0_local": float(bridge_x0),
        "bridge_x1_local": float(bridge_x1),
        "score": float(line_score),
        "valid_hysteresis_late_band": bool(valid_hysteresis_late_band),
        "valid_fresh": bool(
            span_fraction >= 0.72
            and dark_delta >= 8.0
            and shoulder_valid
            and centerline_in_run >= 1.0
            and upper_gap_px >= 3.0
            and lower_gap_px >= 4.0
            and late_prior_plausible
        ),
        "valid_hysteresis": bool(
            span_fraction >= 0.62
            and dark_delta >= 5.0
            and shoulder_valid
            and centerline_in_run >= 1.0
            and upper_gap_px >= 3.0
            and lower_gap_px >= 4.0
            and late_prior_plausible
        ),
    }


def _region_average_score_v2(regions: list[tuple[int, int]], scores: np.ndarray):
    best = None
    for start, end in regions:
        region_scores = scores[start : end + 1]
        if region_scores.size <= 0:
            continue
        average = float(np.mean(region_scores))
        candidate = (average, start, end)
        if best is None or average > best[0] or (average == best[0] and start < best[1]):
            best = candidate
    return best


def _visible_line_acquisition_upper_bound_y_local_v2(
    geometry: dict,
    *,
    previous_attached_y_local: float | None = None,
    droplet_y_local: float | None = None,
):
    rows = geometry["rows"]
    if rows.size <= 0:
        return None
    top_y_local = float(rows[0])
    height = max(1.0, float(geometry.get("height") or (rows[-1] - rows[0] + 1)))
    base_upper_bound_y_local = float(top_y_local + round((height - 1.0) * 0.55))
    hard_cap_y_local = float(top_y_local + round((height - 1.0) * 0.62))
    upper_bound_y_local = float(min(base_upper_bound_y_local, hard_cap_y_local))
    for cue_y_local in (previous_attached_y_local, droplet_y_local):
        if cue_y_local is None:
            continue
        cue_value = float(cue_y_local)
        if cue_value < top_y_local:
            continue
        if cue_value > float(hard_cap_y_local) + 4.0:
            continue
        upper_bound_y_local = max(upper_bound_y_local, min(float(hard_cap_y_local), cue_value + 4.0))
    return float(upper_bound_y_local)


def _visible_line_acquisition_center_y_local_v2(
    geometry: dict,
    *,
    compact_droplet_score: float,
    droplet_y_local: float | None,
    previous_attached_y_local: float | None,
):
    rows = geometry["rows"]
    if rows.size <= 0:
        return None, None, "acquisition_unavailable"

    top_y_local = float(rows[0])
    height = max(1.0, float(geometry.get("height") or (rows[-1] - rows[0] + 1)))
    upper_bound_y_local = _visible_line_acquisition_upper_bound_y_local_v2(
        geometry,
        previous_attached_y_local=previous_attached_y_local,
        droplet_y_local=(droplet_y_local if float(compact_droplet_score) >= 0.55 else None),
    )

    if droplet_y_local is not None and float(compact_droplet_score) >= 0.55:
        center_y_local = float(droplet_y_local)
        source = "compact_droplet_upper_neck"
    elif (
        previous_attached_y_local is not None
        and (
            upper_bound_y_local is None
            or float(previous_attached_y_local) <= float(upper_bound_y_local) + 4.0
        )
    ):
        center_y_local = float(previous_attached_y_local)
        source = "previous_attached_upper_continuity"
    else:
        broad_index = _first_broad_index(geometry["widths"])
        if broad_index is not None:
            center_y_local = float(rows[int(broad_index)])
            source = "first_broad_index"
        else:
            center_y_local = float(top_y_local + round((height - 1.0) * 0.35))
            source = "upper_height_heuristic"

    if upper_bound_y_local is not None:
        center_y_local = float(min(center_y_local, float(upper_bound_y_local)))
    center_y_local = float(max(center_y_local, top_y_local))
    return center_y_local, upper_bound_y_local, source


def _hollow_bulb_guard_v2(
    geometry: dict,
    *,
    contour_completeness_score: float | None,
    candidate_y_local: float | None,
):
    rows = geometry["rows"]
    widths = geometry["widths"].astype(np.float32)
    if rows.size < 12 or widths.size != rows.size:
        return {
            "active": False,
            "candidate_rejected": False,
            "guard_boundary_y_local": None,
            "upper_neck_width_px": None,
            "lower_plateau_width_px": None,
        }

    top_y_local = float(rows[0])
    height = max(1.0, float(geometry.get("height") or (rows[-1] - rows[0] + 1)))
    guard_boundary_y_local = float(top_y_local + round((height - 1.0) * 0.60))
    upper_limit_index = max(4, min(len(widths) - 4, int(round(len(widths) * 0.30))))
    lower_start_index = max(upper_limit_index + 1, int(round(len(widths) * 0.55)))
    upper_widths = widths[:upper_limit_index]
    lower_widths = widths[lower_start_index:]
    if upper_widths.size < 3 or lower_widths.size < 3:
        return {
            "active": False,
            "candidate_rejected": False,
            "guard_boundary_y_local": float(guard_boundary_y_local),
            "upper_neck_width_px": None,
            "lower_plateau_width_px": None,
        }

    upper_neck_width_px = float(np.median(upper_widths))
    lower_plateau_width_px = float(np.median(lower_widths))
    lower_q90 = float(np.percentile(lower_widths, 90))
    upper_q75 = float(np.percentile(upper_widths, 75))
    active = bool(
        float(contour_completeness_score or 0.0) >= 0.82
        and float(height) >= 70.0
        and lower_plateau_width_px >= max(upper_neck_width_px * 1.20, upper_q75 * 1.10)
        and lower_q90 >= upper_q75 * 1.08
    )
    candidate_rejected = bool(
        active
        and candidate_y_local is not None
        and float(candidate_y_local) >= float(guard_boundary_y_local)
    )
    return {
        "active": bool(active),
        "candidate_rejected": bool(candidate_rejected),
        "guard_boundary_y_local": float(guard_boundary_y_local),
        "upper_neck_width_px": float(upper_neck_width_px),
        "lower_plateau_width_px": float(lower_plateau_width_px),
    }


def _visible_line_search_config_v2(
    geometry: dict,
    *,
    neck_metrics: dict | None,
    compact_droplet_score: float = 0.0,
    droplet_y_local: float | None = None,
    previous_attached_y_local: float | None,
    previous_mode_history: tuple[str, ...] | list[str] | None,
    stable_visible_line_y_local: float | None,
    provisional_visible_line_y_local: float | None = None,
    visible_line_streak_length: int,
    missing_visible_line_count: int,
):
    rows = geometry["rows"]
    history_tail = _mode_history_tail(previous_mode_history, length=3)
    recent_visible_history = "visible_nozzle_line" in history_tail
    stable_prior_exists = stable_visible_line_y_local is not None
    provisional_prior_exists = provisional_visible_line_y_local is not None and not stable_prior_exists
    stable_center_index = None
    if stable_prior_exists:
        stable_center_index = _row_index_for_local_y(geometry, int(round(float(stable_visible_line_y_local))))
    provisional_center_index = None
    if provisional_prior_exists:
        provisional_center_index = _row_index_for_local_y(geometry, int(round(float(provisional_visible_line_y_local))))

    neck_is_strong = False
    if neck_metrics is not None and float(neck_metrics.get("score") or 0.0) >= 0.55:
        if stable_visible_line_y_local is None:
            neck_is_strong = True
        else:
            neck_is_strong = abs(float(neck_metrics["neck_y_local"]) - float(stable_visible_line_y_local)) <= 8.0

    acquisition_search_center_y_local = None
    acquisition_upper_bound_y_local = None

    if stable_prior_exists:
        center_index = int(stable_center_index)
        radius = 10
        source = "stable_visible_line_prior"
    elif provisional_prior_exists:
        center_index = int(provisional_center_index)
        radius = 12
        source = "provisional_visible_line_prior"
    elif neck_is_strong:
        center_index = int(neck_metrics["index"])
        radius = 14
        source = "strong_neck"
    else:
        acquisition_center_y_local, acquisition_upper_bound_y_local, source = _visible_line_acquisition_center_y_local_v2(
            geometry,
            compact_droplet_score=float(compact_droplet_score),
            droplet_y_local=droplet_y_local,
            previous_attached_y_local=previous_attached_y_local,
        )
        acquisition_search_center_y_local = acquisition_center_y_local
        if acquisition_center_y_local is None:
            center_index = max(0, int(round(rows.size * 0.22)))
            source = "broad_reacquisition"
        else:
            center_index = _row_index_for_local_y(geometry, int(round(float(acquisition_center_y_local))))
        radius = 18

    return {
        "center_index": int(center_index),
        "center_y_local": float(rows[int(center_index)]),
        "radius_px": int(radius),
        "source": str(source),
        "stable_visible_line_y_local": None if stable_visible_line_y_local is None else float(stable_visible_line_y_local),
        "recent_visible_history": bool(recent_visible_history),
        "stable_prior_exists": bool(stable_prior_exists),
        "provisional_prior_exists": bool(provisional_prior_exists),
        "allow_hysteresis": bool(
            (stable_prior_exists or provisional_prior_exists)
            and (
                int(visible_line_streak_length) >= 1
                or int(missing_visible_line_count) > 0
                or recent_visible_history
            )
        ),
        "acquisition_search_center_y_local": None
        if acquisition_search_center_y_local is None
        else float(acquisition_search_center_y_local),
        "acquisition_upper_bound_y_local": None
        if acquisition_upper_bound_y_local is None
        else float(acquisition_upper_bound_y_local),
    }


def _visible_line_context_v2(
    geometry: dict,
    *,
    neck_metrics: dict | None,
    compact_droplet_score: float = 0.0,
    droplet_y_local: float | None = None,
    previous_attached_y_local: float | None,
    previous_mode_history: tuple[str, ...] | list[str] | None,
    stable_visible_line_y_local: float | None,
    provisional_visible_line_y_local: float | None = None,
    visible_line_streak_length: int,
    missing_visible_line_count: int,
    recent_attached_width_median_px: float | None,
    recent_attached_center_x_local: float | None,
):
    search_config = _visible_line_search_config_v2(
        geometry,
        neck_metrics=neck_metrics,
        compact_droplet_score=float(compact_droplet_score),
        droplet_y_local=droplet_y_local,
        previous_attached_y_local=previous_attached_y_local,
        previous_mode_history=previous_mode_history,
        stable_visible_line_y_local=stable_visible_line_y_local,
        provisional_visible_line_y_local=provisional_visible_line_y_local,
        visible_line_streak_length=int(visible_line_streak_length),
        missing_visible_line_count=int(missing_visible_line_count),
    )
    contour_metrics = _contour_completeness_metrics_v2(
        geometry,
        search_center_index=int(search_config["center_index"]),
        search_radius_px=int(search_config["radius_px"]),
        recent_attached_width_median_px=recent_attached_width_median_px,
        recent_attached_center_x_local=recent_attached_center_x_local,
    )
    return search_config, contour_metrics


def _contour_completeness_metrics_v2(
    geometry: dict,
    *,
    search_center_index: int,
    search_radius_px: int,
    recent_attached_width_median_px: float | None,
    recent_attached_center_x_local: float | None,
):
    rows = geometry["rows"]
    start_index = max(0, int(search_center_index) - int(search_radius_px))
    end_index = min(len(rows) - 1, int(search_center_index) + int(search_radius_px))
    window_rows = rows[start_index : end_index + 1]
    if window_rows.size <= 0:
        return None

    window_widths = geometry["widths"][start_index : end_index + 1].astype(np.float32)
    window_lefts = geometry["lefts"][start_index : end_index + 1].astype(np.float32)
    window_rights = geometry["rights"][start_index : end_index + 1].astype(np.float32)
    window_centerlines = geometry["centerlines"][start_index : end_index + 1].astype(np.float32)
    width_median = float(np.median(window_widths))
    width_iqr = float(np.percentile(window_widths, 75) - np.percentile(window_widths, 25))
    width_continuity = float(max(0.0, min(1.0, 1.0 - (width_iqr / max(1.0, width_median)))))
    reference_center_x = (
        float(recent_attached_center_x_local)
        if recent_attached_center_x_local is not None
        else float(np.median(window_centerlines))
    )
    left_offsets = reference_center_x - window_lefts
    right_offsets = window_rights - reference_center_x
    offset_floor = max(4.0, width_median * 0.20)
    balance = np.minimum(left_offsets, right_offsets) / np.maximum(1.0, np.maximum(left_offsets, right_offsets))
    bilateral_mask = np.logical_and.reduce(
        (
            left_offsets >= offset_floor,
            right_offsets >= offset_floor,
            balance >= 0.55,
        )
    )
    bilateral_row_fraction = float(np.count_nonzero(bilateral_mask) / float(len(window_widths)))
    width_ratio = 1.0
    clipped_warning = False
    if recent_attached_width_median_px is not None and float(recent_attached_width_median_px) > 0.0:
        width_ratio = float(width_median / float(recent_attached_width_median_px))
        historical_half_width = float(recent_attached_width_median_px) / 2.0
        current_left_median = float(np.median(left_offsets))
        current_right_median = float(np.median(right_offsets))
        bilateral_inward = bool(
            current_left_median <= (historical_half_width - 3.0)
            and current_right_median <= (historical_half_width - 3.0)
        )
        clipped_warning = bool(width_ratio < 0.75 and not bilateral_inward)
    completeness = float(
        max(
            0.0,
            min(
                1.0,
                (0.45 * bilateral_row_fraction)
                + (0.35 * width_continuity)
                + (0.20 * max(0.0, min(1.0, width_ratio))),
            ),
        )
    )
    if clipped_warning:
        completeness *= 0.55
    return {
        "start_index": int(start_index),
        "end_index": int(end_index),
        "width_median_px": width_median,
        "width_iqr_px": width_iqr,
        "reference_center_x_local": float(reference_center_x),
        "bilateral_row_fraction": bilateral_row_fraction,
        "completeness_score": float(completeness),
        "width_ratio": float(width_ratio),
        "clipped_warning": bool(clipped_warning),
    }


def _late_widening_metrics_v2(
    geometry: dict,
    contour_metrics: dict | None,
    *,
    search_center_y_local: float,
    stable_visible_line_y_local: float | None,
):
    if (
        stable_visible_line_y_local is None
        or contour_metrics is None
        or float(contour_metrics.get("completeness_score") or 0.0) < 0.38
    ):
        return None

    rows = geometry["rows"]
    widths = geometry["widths"].astype(np.float32)
    lefts = geometry["lefts"].astype(np.float32)
    rights = geometry["rights"].astype(np.float32)
    if rows.size < 8:
        return None

    target_y_local = float(stable_visible_line_y_local if stable_visible_line_y_local is not None else search_center_y_local)
    y_radius = 8
    start_y = float(target_y_local) - float(y_radius)
    end_y = float(target_y_local) + float(y_radius)
    valid_indices = [index for index, row_y in enumerate(rows) if start_y <= float(row_y) <= end_y]
    if len(valid_indices) < 5:
        return None

    smooth_widths = _smooth_profile(widths, sigma=1.2)
    max_width = float(np.max([smooth_widths[index] for index in valid_indices]))
    if max_width <= 0.0:
        return None

    plateau_threshold = float(max_width - max(1.5, max_width * 0.05))
    plateau_mask = np.array([float(smooth_widths[index]) >= plateau_threshold for index in valid_indices], dtype=bool)
    plateau_regions = _regions_from_mask(plateau_mask)
    if not plateau_regions:
        return None

    chosen_region = None
    chosen_region_abs_indices = None
    for start, end in plateau_regions:
        absolute_indices = [int(valid_indices[offset]) for offset in range(int(start), int(end) + 1)]
        if not absolute_indices:
            continue
        top_y = float(rows[absolute_indices[0]])
        bottom_y = float(rows[absolute_indices[-1]])
        distance_from_prior = 0.0
        if target_y_local < top_y:
            distance_from_prior = float(top_y - target_y_local)
        elif target_y_local > bottom_y:
            distance_from_prior = float(target_y_local - bottom_y)
        mean_width = float(np.mean([smooth_widths[index] for index in absolute_indices]))
        candidate = (
            float(distance_from_prior),
            -float(mean_width),
            -int(len(absolute_indices)),
            float(top_y),
        )
        if chosen_region is None or candidate < chosen_region:
            chosen_region = candidate
            chosen_region_abs_indices = absolute_indices
    if not chosen_region_abs_indices:
        return None

    band_top_index = int(chosen_region_abs_indices[0])
    band_bottom_index = int(chosen_region_abs_indices[-1])
    band_mid_y = float(rows[int(round((band_top_index + band_bottom_index) / 2.0))])
    selected_index = min(
        chosen_region_abs_indices,
        key=lambda idx: (
            abs(float(rows[idx]) - float(target_y_local)),
            0 if float(rows[idx]) >= float(band_mid_y) else 1,
            -float(rows[idx]),
        ),
    )

    before_indices = [idx for idx in valid_indices if idx < band_top_index][-4:]
    baseline_width = (
        float(np.min([smooth_widths[idx] for idx in before_indices]))
        if before_indices
        else float(np.min([smooth_widths[idx] for idx in chosen_region_abs_indices]))
    )
    if baseline_width <= 0.0:
        baseline_width = float(max_width)
    increase_fraction = float(max(0.0, (max_width - baseline_width) / max(1e-6, baseline_width)))

    reference_indices = before_indices if before_indices else [band_top_index]
    left_expand = float(
        np.median([lefts[idx] for idx in reference_indices]) - np.median([lefts[idx] for idx in chosen_region_abs_indices])
    )
    right_expand = float(
        np.median([rights[idx] for idx in chosen_region_abs_indices]) - np.median([rights[idx] for idx in reference_indices])
    )
    plateau_height_px = int(max(1, int(rows[band_bottom_index]) - int(rows[band_top_index]) + 1))
    selected_distance = abs(float(rows[selected_index]) - float(target_y_local))
    score = float(
        max(
            0.0,
            min(
                1.0,
                (0.42 * _normalize_range(increase_fraction, 0.04, 0.25))
                + (0.22 * _normalize_range(min(left_expand, right_expand), 1.0, 6.0))
                + (0.20 * float(contour_metrics.get("completeness_score") or 0.0))
                + (0.10 * _normalize_range(8.0 - selected_distance, 0.0, 8.0))
                + (0.06 * _normalize_range(float(plateau_height_px), 1.0, 6.0)),
            ),
        )
    )
    if increase_fraction < 0.04 and min(left_expand, right_expand) < 1.0:
        return None

    return {
        "index": int(selected_index),
        "raw_x_local": float(geometry["centerlines"][selected_index]),
        "raw_y_local": float(rows[selected_index]),
        "score": score,
        "increase_fraction": float(increase_fraction),
        "left_expand_px": float(left_expand),
        "right_expand_px": float(right_expand),
        "plateau_top_y_local": float(rows[band_top_index]),
        "plateau_bottom_y_local": float(rows[band_bottom_index]),
        "plateau_height_px": int(plateau_height_px),
        "plateau_max_width_px": float(max_width),
    }


def _visible_line_metrics_v2(
    search_gray: np.ndarray,
    geometry: dict,
    profiles: dict,
    *,
    neck_metrics: dict | None,
    compact_droplet_score: float = 0.0,
    droplet_y_local: float | None = None,
    previous_attached_y_local: float | None,
    previous_mode_history: tuple[str, ...] | list[str] | None,
    stable_visible_line_y_local: float | None,
    provisional_visible_line_y_local: float | None = None,
    visible_line_streak_length: int,
    missing_visible_line_count: int,
    attached_support_score: float,
    recent_attached_width_median_px: float | None,
    recent_attached_center_x_local: float | None,
):
    rows = geometry["rows"]
    if rows.size < 12:
        return None

    search_config = _visible_line_search_config_v2(
        geometry,
        neck_metrics=neck_metrics,
        compact_droplet_score=float(compact_droplet_score),
        droplet_y_local=droplet_y_local,
        previous_attached_y_local=previous_attached_y_local,
        previous_mode_history=previous_mode_history,
        stable_visible_line_y_local=stable_visible_line_y_local,
        provisional_visible_line_y_local=provisional_visible_line_y_local,
        visible_line_streak_length=int(visible_line_streak_length),
        missing_visible_line_count=int(missing_visible_line_count),
    )
    contour_metrics = _contour_completeness_metrics_v2(
        geometry,
        search_center_index=int(search_config["center_index"]),
        search_radius_px=int(search_config["radius_px"]),
        recent_attached_width_median_px=recent_attached_width_median_px,
        recent_attached_center_x_local=recent_attached_center_x_local,
    )
    contour_completeness_score = None if contour_metrics is None else float(contour_metrics.get("completeness_score") or 0.0)
    stable_prior_y_local = search_config["stable_visible_line_y_local"]
    acquisition_search_center_y_local = search_config.get("acquisition_search_center_y_local")
    acquisition_upper_bound_y_local = search_config.get("acquisition_upper_bound_y_local")
    center_index = int(search_config["center_index"])
    radius = int(search_config["radius_px"])
    start_index = max(0, center_index - radius)
    end_index = min(len(rows) - 1, center_index + radius)

    per_index_metrics = {}
    strict_scores = np.full(end_index - start_index + 1, -1.0, dtype=np.float32)
    strict_valid_mask = np.zeros(end_index - start_index + 1, dtype=bool)
    relaxed_scores = np.full(end_index - start_index + 1, -1.0, dtype=np.float32)
    relaxed_valid_mask = np.zeros(end_index - start_index + 1, dtype=bool)
    for absolute_index in range(start_index, end_index + 1):
        metric = _visible_line_row_bridge_metrics_v2(
            search_gray,
            geometry,
            profiles,
            absolute_index,
            stable_visible_line_y_local=search_config["stable_visible_line_y_local"],
            contour_completeness_score=contour_completeness_score,
        )
        if metric is None:
            continue
        used_hysteresis = bool(
            search_config["allow_hysteresis"]
            and search_config["stable_visible_line_y_local"] is not None
            and abs(float(metric["row_y_local"]) - float(search_config["stable_visible_line_y_local"])) <= 12.0
            and bool(metric["valid_hysteresis"] or metric.get("valid_hysteresis_late_band"))
        )
        metric["used_hysteresis"] = bool(used_hysteresis)
        per_index_metrics[int(absolute_index)] = metric
        if bool(metric["valid_fresh"]) or bool(metric["used_hysteresis"]):
            strict_scores[absolute_index - start_index] = float(metric["score"])
            strict_valid_mask[absolute_index - start_index] = True
        relaxed_ok = bool(
            search_config["stable_prior_exists"]
            and int(visible_line_streak_length) >= 3
            and int(missing_visible_line_count) <= 2
            and float(attached_support_score) >= 0.10
            and search_config["stable_visible_line_y_local"] is not None
            and abs(float(metric["row_y_local"]) - float(search_config["stable_visible_line_y_local"])) <= 6.0
            and float(metric["span_fraction"]) >= 0.50
            and float(metric["dark_delta"]) >= 3.0
            and float(metric["vertical_overlap"]) >= 0.50
            and float(metric["centerline_in_run"]) >= 1.0
        )
        metric["relaxed_fallback_valid"] = bool(relaxed_ok)
        if relaxed_ok:
            relaxed_scores[absolute_index - start_index] = float(metric["score"])
            relaxed_valid_mask[absolute_index - start_index] = True

    used_relaxed_fallback = False
    local_scores = strict_scores
    valid_mask = strict_valid_mask
    if not np.any(valid_mask) and np.any(relaxed_valid_mask):
        used_relaxed_fallback = True
        local_scores = relaxed_scores
        valid_mask = relaxed_valid_mask

    if not np.any(valid_mask):
        widening_only = None
        if (
            search_config["stable_prior_exists"]
            and search_config["stable_visible_line_y_local"] is not None
            and int(missing_visible_line_count) <= 3
            and float(attached_support_score) >= 0.10
            and bool(search_config["recent_visible_history"])
        ):
            widening_only = _late_widening_metrics_v2(
                geometry,
                contour_metrics,
                search_center_y_local=float(search_config["center_y_local"]),
                stable_visible_line_y_local=search_config["stable_visible_line_y_local"],
            )
            if widening_only is not None:
                plateau_y_local = float(widening_only["raw_y_local"])
                stable_prior_y_local = float(search_config["stable_visible_line_y_local"])
                if not (
                    float(contour_completeness_score or 0.0) >= 0.85
                    and abs(float(plateau_y_local) - float(stable_prior_y_local)) <= 4.0
                ):
                    widening_only = None
        if widening_only is None:
            return None
        fallback_score = float(max(float(widening_only["score"]), float(MODE_SCORE_THRESHOLDS["visible_line_keep"]) + 0.04))
        return {
            "index": int(widening_only["index"]),
            "raw_x_local": float(widening_only["raw_x_local"]),
            "raw_y_local": float(widening_only["raw_y_local"]),
            "line_band_y_local": float(widening_only["raw_y_local"]),
            "score": float(fallback_score),
            "upper_peak_y_local": None,
            "lower_peak_y_local": None,
            "search_center_y_local": float(search_config["center_y_local"]),
            "search_radius_px": int(search_config["radius_px"]),
            "band_top_y_local": None,
            "band_bottom_y_local": None,
            "band_height_px": None,
            "span_width_px": None,
            "span_fraction": None,
            "dark_delta": None,
            "vertical_overlap": None,
            "used_hysteresis": False,
            "used_relaxed_fallback": True,
            "used_plateau_only_fallback": True,
            "valid_late_band": False,
            "plateau_mode": "tracked_late_plateau",
            "plateau_suppressed_on_acquisition": False,
            "hollow_bulb_guard_active": False,
            "rejected_by_hollow_bulb_guard": False,
            "rejected_by_upper_cue_conflict": False,
            "lower_peak_prior_constrained": False,
            "effective_lower_peak_y_local": None,
            "bridge_x0_local": None,
            "bridge_x1_local": None,
            "stable_visible_line_y_local": None if search_config["stable_visible_line_y_local"] is None else float(search_config["stable_visible_line_y_local"]),
            "acquisition_search_center_y_local": None if acquisition_search_center_y_local is None else float(acquisition_search_center_y_local),
            "acquisition_upper_bound_y_local": None if acquisition_upper_bound_y_local is None else float(acquisition_upper_bound_y_local),
            "contour_completeness_score": None if contour_metrics is None else float(contour_metrics["completeness_score"]),
            "contour_bilateral_row_fraction": None if contour_metrics is None else float(contour_metrics["bilateral_row_fraction"]),
            "contour_width_median_px": None if contour_metrics is None else float(contour_metrics["width_median_px"]),
            "contour_width_iqr_px": None if contour_metrics is None else float(contour_metrics["width_iqr_px"]),
            "contour_clipped_warning": False if contour_metrics is None else bool(contour_metrics["clipped_warning"]),
            "late_widening_y_local": float(widening_only["raw_y_local"]),
            "late_widening_score": float(widening_only["score"]),
            "late_widening_used": True,
            "late_plateau_band_top_y_local": widening_only.get("plateau_top_y_local"),
            "late_plateau_band_bottom_y_local": widening_only.get("plateau_bottom_y_local"),
            "late_plateau_picked_y_local": float(widening_only["raw_y_local"]),
            "bridge_suppressed_by_clipped_contour": False,
            "bridge_suppressed_by_plateau": False,
            "bridge_suppressed_by_prior_conflict": False,
            "bridge_delta_from_prior_px": None,
            "plateau_delta_from_prior_px": None,
        }

    max_score = float(np.max(local_scores[valid_mask]))
    keep_threshold = float(MODE_SCORE_THRESHOLDS["visible_line_keep"])
    enter_threshold = float(MODE_SCORE_THRESHOLDS["visible_line_enter"])
    active_threshold = max(keep_threshold, max_score * 0.85)
    active_mask = np.logical_and(valid_mask, local_scores >= active_threshold)
    preferred_regions = _regions_from_mask(active_mask)
    chosen = _region_average_score_v2(preferred_regions, local_scores)
    if chosen is None:
        chosen_score = float(np.max(local_scores[valid_mask]))
        chosen_start = int(np.flatnonzero(local_scores == chosen_score)[0])
        chosen_end = int(chosen_start)
    else:
        chosen_score, chosen_start, chosen_end = chosen

    band_absolute_indices = list(range(int(start_index + chosen_start), int(start_index + chosen_end) + 1))
    if not band_absolute_indices:
        band_absolute_indices = [int(start_index + chosen_start)]
    band_rows = [int(rows[index]) for index in band_absolute_indices]
    band_top_y_local = int(min(band_rows))
    band_bottom_y_local = int(max(band_rows))
    band_height_px = int(max(1, band_bottom_y_local - band_top_y_local + 1))
    stable_prior_y_local = search_config["stable_visible_line_y_local"]

    if band_height_px <= 4:
        absolute_index = int(band_absolute_indices[0])
    else:
        target_y_local = None
        if (
            stable_prior_y_local is not None
            and (
                (band_top_y_local - 2.0) <= float(stable_prior_y_local) <= (band_bottom_y_local + 2.0)
                or min(
                    abs(float(band_top_y_local) - float(stable_prior_y_local)),
                    abs(float(band_bottom_y_local) - float(stable_prior_y_local)),
                ) <= 6.0
            )
        ):
            target_y_local = float(stable_prior_y_local)
        elif acquisition_upper_bound_y_local is not None:
            target_y_local = float(acquisition_upper_bound_y_local)
        else:
            peak_index = max(band_absolute_indices, key=lambda idx: float(local_scores[idx - start_index]))
            peak_metric = per_index_metrics.get(int(peak_index))
            if peak_metric is not None and peak_metric.get("lower_peak_y_local") is not None:
                target_y_local = float(peak_metric["lower_peak_y_local"]) - 2.0
        if target_y_local is None:
            absolute_index = int(band_absolute_indices[0])
        else:
            absolute_index = min(
                band_absolute_indices,
                key=lambda idx: (
                    abs(float(rows[idx]) - float(target_y_local)),
                    -float(local_scores[idx - start_index]),
                    idx,
                ),
            )
    chosen_metric = per_index_metrics.get(absolute_index)
    if chosen_metric is None:
        return None

    if stable_prior_y_local is not None:
        near_prior_candidates = [
            (candidate_index, metric)
            for candidate_index, metric in per_index_metrics.items()
            if abs(float(metric["row_y_local"]) - float(stable_prior_y_local)) <= 4.0
            and bool(metric.get("used_hysteresis"))
        ]
        if near_prior_candidates:
            near_prior_index, near_prior_metric = sorted(
                near_prior_candidates,
                key=lambda item: (
                    abs(float(item[1]["row_y_local"]) - float(stable_prior_y_local)),
                    -float(item[1]["score"]),
                    -float(item[1]["row_y_local"]),
                ),
            )[0]
            if (
                bool(chosen_metric.get("valid_fresh"))
                and not bool(chosen_metric.get("used_hysteresis"))
                and (
                    float(rows[absolute_index]) <= float(stable_prior_y_local) - 8.0
                    or (
                        int(band_height_px) >= 5
                        and min(
                            abs(float(band_top_y_local) - float(stable_prior_y_local)),
                            abs(float(band_bottom_y_local) - float(stable_prior_y_local)),
                        ) <= 4.0
                        and float(rows[absolute_index]) <= float(stable_prior_y_local) - 4.0
                    )
                )
            ):
                absolute_index = int(near_prior_index)
                chosen_metric = dict(near_prior_metric)
                band_absolute_indices = [int(near_prior_index)]
                band_top_y_local = int(round(float(chosen_metric["row_y_local"])))
                band_bottom_y_local = int(round(float(chosen_metric["row_y_local"])))
                band_height_px = 1

    chosen_y_local = int(rows[absolute_index])
    hollow_bulb_guard = _hollow_bulb_guard_v2(
        geometry,
        contour_completeness_score=contour_completeness_score,
        candidate_y_local=float(chosen_y_local),
    )
    hollow_bulb_guard_active = bool(hollow_bulb_guard.get("active"))
    rejected_by_hollow_bulb_guard = bool(hollow_bulb_guard.get("candidate_rejected"))
    acquisition_row_out_of_bounds = bool(
        stable_prior_y_local is None
        and acquisition_upper_bound_y_local is not None
        and float(chosen_y_local) > float(acquisition_upper_bound_y_local)
    )
    if (
        stable_prior_y_local is not None
        and (float(chosen_y_local) < float(stable_prior_y_local) - 6.0)
        and not (
            float(chosen_metric["score"]) >= float(MODE_SCORE_THRESHOLDS["visible_line_strong_override"])
            and float(chosen_metric["span_fraction"]) >= 0.85
        )
    ):
        return None

    threshold_for_choice = (
        float(keep_threshold)
        if bool(chosen_metric.get("used_hysteresis")) or bool(used_relaxed_fallback)
        else float(enter_threshold)
    )
    if float(chosen_metric["score"]) < threshold_for_choice:
        return None

    widening_metrics = _late_widening_metrics_v2(
        geometry,
        contour_metrics,
        search_center_y_local=float(search_config["center_y_local"]),
        stable_visible_line_y_local=search_config["stable_visible_line_y_local"],
    )
    bridge_suppressed_by_clipped_contour = False
    bridge_suppressed_by_plateau = False
    bridge_suppressed_by_prior_conflict = False
    late_widening_used = False
    plateau_suppressed_on_acquisition = bool(stable_prior_y_local is None)
    plateau_mode = "acquisition_upper_boundary" if stable_prior_y_local is None else "tracked_late_plateau"
    selected_y_local = int(chosen_y_local)
    selected_x_local = float(_centerline_x_at_local_y(geometry, chosen_y_local))
    selected_score = float(chosen_metric["score"])
    selected_upper_peak_y_local = float(chosen_metric["upper_peak_y_local"])
    selected_lower_peak_y_local = float(chosen_metric["lower_peak_y_local"])
    selected_bridge_x0_local = float(chosen_metric["bridge_x0_local"])
    selected_bridge_x1_local = float(chosen_metric["bridge_x1_local"])
    bridge_delta_from_prior_px = None if stable_prior_y_local is None else float(selected_y_local) - float(stable_prior_y_local)
    plateau_delta_from_prior_px = None

    if widening_metrics is not None:
        widening_y_local = float(widening_metrics["raw_y_local"])
        plateau_delta_from_prior_px = None if stable_prior_y_local is None else float(widening_y_local) - float(stable_prior_y_local)
        if stable_prior_y_local is not None:
            bridge_too_high = bool(float(selected_y_local) < float(stable_prior_y_local) - 6.0)
            bridge_far_from_prior = bool(abs(float(selected_y_local) - float(stable_prior_y_local)) > 4.0)
            widening_closer_to_prior = bool(
                abs(float(widening_y_local) - float(stable_prior_y_local))
                < abs(float(selected_y_local) - float(stable_prior_y_local))
            )
            widening_close_to_prior = bool(abs(float(widening_y_local) - float(stable_prior_y_local)) <= 4.0)
            plateau_near_prior = bool(abs(float(widening_y_local) - float(stable_prior_y_local)) <= 3.0)
            bridge_outside_plateau_band = bool(
                widening_metrics.get("plateau_top_y_local") is not None
                and widening_metrics.get("plateau_bottom_y_local") is not None
                and (
                    float(selected_y_local) < float(widening_metrics["plateau_top_y_local"]) - 2.0
                    or float(selected_y_local) > float(widening_metrics["plateau_bottom_y_local"]) + 2.0
                )
            )
            prefer_widening = bool(
                (
                    bool(used_relaxed_fallback)
                    and widening_close_to_prior
                    and float(widening_metrics["score"]) >= max(0.34, float(selected_score) * 0.60)
                )
                or (
                    bridge_too_high
                    and widening_closer_to_prior
                    and float(widening_metrics["score"]) >= 0.34
                )
                or (
                    bridge_far_from_prior
                    and plateau_near_prior
                    and float(widening_metrics["score"]) >= 0.32
                )
                or (
                    float(selected_y_local) <= float(stable_prior_y_local) - 4.0
                    and abs(float(widening_y_local) - float(stable_prior_y_local)) <= 2.0
                    and float(widening_metrics["score"]) >= 0.55
                    and (
                        float(selected_score) - float(widening_metrics["score"]) <= 0.12
                        or bridge_outside_plateau_band
                    )
                )
            )
            if (
                bool(contour_metrics is not None and contour_metrics.get("clipped_warning"))
                and widening_closer_to_prior
                and float(widening_metrics["score"]) >= 0.34
                and (bridge_too_high or bool(used_relaxed_fallback))
            ):
                bridge_suppressed_by_clipped_contour = True
                prefer_widening = True
            if (
                bridge_too_high
                and widening_closer_to_prior
                and float(widening_metrics["score"]) >= max(0.28, float(selected_score) * 0.55)
            ):
                bridge_suppressed_by_plateau = True
                prefer_widening = True
            if (
                bridge_far_from_prior
                and plateau_near_prior
                and abs(float(selected_y_local) - float(widening_y_local)) > 5.0
            ):
                bridge_suppressed_by_prior_conflict = True
                prefer_widening = True
            if (
                float(selected_y_local) <= float(stable_prior_y_local) - 4.0
                and abs(float(widening_y_local) - float(stable_prior_y_local)) <= 2.0
                and float(widening_metrics["score"]) >= 0.55
                and (
                    float(selected_score) - float(widening_metrics["score"]) <= 0.12
                    or bridge_outside_plateau_band
                )
            ):
                bridge_suppressed_by_prior_conflict = True
                prefer_widening = True
        else:
            prefer_widening = False
        if prefer_widening:
            late_widening_used = True
            selected_y_local = int(round(widening_y_local))
            selected_x_local = float(widening_metrics["raw_x_local"])
            selected_score = float(max(float(widening_metrics["score"]), threshold_for_choice))
            selected_upper_peak_y_local = None
            selected_lower_peak_y_local = None
            selected_bridge_x0_local = None
            selected_bridge_x1_local = None

    return {
        "index": int(absolute_index),
        "raw_x_local": float(selected_x_local),
        "raw_y_local": float(selected_y_local),
        "line_band_y_local": float(selected_y_local),
        "score": float(selected_score),
        "upper_peak_y_local": selected_upper_peak_y_local,
        "lower_peak_y_local": selected_lower_peak_y_local,
        "search_center_y_local": float(search_config["center_y_local"]),
        "search_radius_px": int(search_config["radius_px"]),
        "band_top_y_local": float(band_top_y_local),
        "band_bottom_y_local": float(band_bottom_y_local),
        "band_height_px": int(band_height_px),
        "span_width_px": int(chosen_metric["span_width_px"]),
        "span_fraction": float(chosen_metric["span_fraction"]),
        "dark_delta": float(chosen_metric["dark_delta"]),
        "vertical_overlap": float(chosen_metric["vertical_overlap"]),
        "used_hysteresis": bool(chosen_metric.get("used_hysteresis")),
        "used_relaxed_fallback": bool(used_relaxed_fallback),
        "used_plateau_only_fallback": False,
        "valid_late_band": bool(chosen_metric.get("valid_hysteresis_late_band")),
        "plateau_mode": plateau_mode,
        "plateau_suppressed_on_acquisition": bool(plateau_suppressed_on_acquisition),
        "hollow_bulb_guard_active": bool(hollow_bulb_guard_active),
        "rejected_by_hollow_bulb_guard": bool(rejected_by_hollow_bulb_guard),
        "rejected_by_upper_cue_conflict": False,
        "lower_peak_prior_constrained": bool(chosen_metric.get("lower_peak_prior_constrained")),
        "effective_lower_peak_y_local": chosen_metric.get("effective_lower_peak_y_local"),
        "bridge_x0_local": selected_bridge_x0_local,
        "bridge_x1_local": selected_bridge_x1_local,
        "stable_visible_line_y_local": None if stable_prior_y_local is None else float(stable_prior_y_local),
        "acquisition_search_center_y_local": None if acquisition_search_center_y_local is None else float(acquisition_search_center_y_local),
        "acquisition_upper_bound_y_local": None if acquisition_upper_bound_y_local is None else float(acquisition_upper_bound_y_local),
        "acquisition_row_out_of_bounds": bool(acquisition_row_out_of_bounds),
        "contour_completeness_score": None if contour_metrics is None else float(contour_metrics["completeness_score"]),
        "contour_bilateral_row_fraction": None if contour_metrics is None else float(contour_metrics["bilateral_row_fraction"]),
        "contour_width_median_px": None if contour_metrics is None else float(contour_metrics["width_median_px"]),
        "contour_width_iqr_px": None if contour_metrics is None else float(contour_metrics["width_iqr_px"]),
        "contour_clipped_warning": False if contour_metrics is None else bool(contour_metrics["clipped_warning"]),
        "late_widening_y_local": None if widening_metrics is None else float(widening_metrics["raw_y_local"]),
        "late_widening_score": None if widening_metrics is None else float(widening_metrics["score"]),
        "late_widening_used": bool(late_widening_used),
        "late_plateau_band_top_y_local": None if widening_metrics is None else widening_metrics.get("plateau_top_y_local"),
        "late_plateau_band_bottom_y_local": None if widening_metrics is None else widening_metrics.get("plateau_bottom_y_local"),
        "late_plateau_picked_y_local": None if widening_metrics is None else float(widening_metrics["raw_y_local"]),
        "bridge_suppressed_by_clipped_contour": bool(bridge_suppressed_by_clipped_contour),
        "bridge_suppressed_by_plateau": bool(bridge_suppressed_by_plateau),
        "bridge_suppressed_by_prior_conflict": bool(bridge_suppressed_by_prior_conflict),
        "bridge_delta_from_prior_px": bridge_delta_from_prior_px,
        "plateau_delta_from_prior_px": plateau_delta_from_prior_px,
    }


def _top_roi_bounds_v2(search_gray: np.ndarray, *, previous_x_local: float | None, previous_y_local: float | None):
    height, width = search_gray.shape[:2]
    center_x = int(round(previous_x_local)) if previous_x_local is not None else int(round(width / 2.0))
    default_y = min(height - 1, max(40, int(round(height * 0.45))))
    center_y = int(round(previous_y_local)) if previous_y_local is not None else default_y
    half_width = min(max(36, width // 5), max(36, width // 2))
    half_height = min(58, max(36, height // 5))
    return {
        "x0": int(max(0, center_x - half_width)),
        "x1": int(min(width, center_x + half_width)),
        "y0": int(max(0, center_y - half_height)),
        "y1": int(min(height, center_y + half_height)),
    }


def _append_unique_y_center_v2(values: list[float], candidate_y_local: float | None):
    if candidate_y_local is None:
        return
    value = float(candidate_y_local)
    for existing in values:
        if abs(float(existing) - value) <= 0.5:
            return
    values.append(value)


def _only_nozzle_roi_center_candidates_v2(
    *,
    previous_y_local: float | None,
    stable_visible_line_y_local: float | None,
    previous_tracked_y_local: float | None,
):
    centers: list[float | None] = []
    _append_unique_y_center_v2(centers, stable_visible_line_y_local)
    _append_unique_y_center_v2(centers, previous_tracked_y_local)
    if stable_visible_line_y_local is not None:
        _append_unique_y_center_v2(centers, float(stable_visible_line_y_local) - 4.0)
        _append_unique_y_center_v2(centers, float(stable_visible_line_y_local) + 4.0)
    previous_y_plausible = bool(
        previous_y_local is not None
        and (
            (stable_visible_line_y_local is not None and abs(float(previous_y_local) - float(stable_visible_line_y_local)) <= 12.0)
            or (previous_tracked_y_local is not None and abs(float(previous_y_local) - float(previous_tracked_y_local)) <= 12.0)
            or (stable_visible_line_y_local is None and previous_tracked_y_local is None)
        )
    )
    if previous_y_plausible:
        _append_unique_y_center_v2(centers, previous_y_local)
    if not centers:
        centers.append(None)
    return centers


def _detect_only_nozzle_candidate_in_roi_v2(
    roi_gray: np.ndarray,
    *,
    roi: dict,
    previous_x_local: float | None,
    stable_visible_line_y_local: float | None,
    attached_support_score: float,
):
    if roi_gray.size <= 0:
        return None

    transition_scoring_used = bool(
        stable_visible_line_y_local is not None
        and float(attached_support_score) < float(MODE_SCORE_THRESHOLDS["attached_support_low"])
    )
    blurred = cv2.GaussianBlur(roi_gray, (0, 0), 2.0)
    otsu_threshold, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    whole_roi_contours: list[np.ndarray] = []
    if int(otsu_threshold) > 0:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        whole_roi_contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    prior_band_contours: list[np.ndarray] = []
    if transition_scoring_used and stable_visible_line_y_local is not None:
        band_center_local = float(stable_visible_line_y_local) - float(roi["y0"])
        band_half_height = 10
        band_y0 = max(0, int(round(band_center_local)) - band_half_height)
        band_y1 = min(roi_gray.shape[0], int(round(band_center_local)) + band_half_height + 1)
        if band_y1 - band_y0 >= 3:
            band_crop = roi_gray[band_y0:band_y1, :]
            band_blurred = cv2.GaussianBlur(band_crop, (0, 0), 2.0)
            band_threshold, band_mask_crop = cv2.threshold(
                band_blurred,
                0,
                255,
                cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
            )
            if int(band_threshold) > 0:
                band_mask_crop = cv2.morphologyEx(
                    band_mask_crop,
                    cv2.MORPH_CLOSE,
                    np.ones((3, 1), np.uint8),
                )
                band_mask_crop = cv2.morphologyEx(
                    band_mask_crop,
                    cv2.MORPH_CLOSE,
                    np.ones((3, 3), np.uint8),
                )
                band_mask = np.zeros_like(roi_gray, dtype=np.uint8)
                band_mask[band_y0:band_y1, :] = band_mask_crop
                prior_band_contours, _hierarchy = cv2.findContours(
                    band_mask,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                )

    if not whole_roi_contours and not prior_band_contours:
        return None

    candidates: list[dict] = []
    def _append_candidate(contour: np.ndarray, *, candidate_source: str):
        area = float(cv2.contourArea(contour))
        if area < 12.0 or area > 1600.0:
            return
        perimeter = float(cv2.arcLength(contour, True))
        compactness = 0.0 if perimeter <= 0.0 else float(max(0.0, min(1.0, (4.0 * np.pi * area) / (perimeter * perimeter))))
        moments = cv2.moments(contour)
        if moments["m00"] > 0.0:
            centroid_x = float(moments["m10"] / moments["m00"])
            centroid_y = float(moments["m01"] / moments["m00"])
        else:
            centroid_x = float(np.mean(contour[:, 0, 0]))
            centroid_y = float(np.mean(contour[:, 0, 1]))

        ellipse_ratio = 2.5
        if len(contour) >= 5:
            (_center, (axis_a, axis_b), _angle) = cv2.fitEllipse(contour)
            major_axis = float(max(axis_a, axis_b))
            minor_axis = float(min(axis_a, axis_b))
            ellipse_ratio = float(major_axis / max(1e-6, minor_axis))

        proximity_score = 0.55
        if previous_x_local is not None and roi.get("center_y_local") is not None:
            distance = float(
                np.hypot(
                    (centroid_x + roi["x0"]) - float(previous_x_local),
                    (centroid_y + roi["y0"]) - float(roi["center_y_local"]),
                )
            )
            proximity_score = _normalize_range(32.0 - distance, 0.0, 32.0)

        distance_from_stable = (
            abs((centroid_y + roi["y0"]) - float(stable_visible_line_y_local))
            if stable_visible_line_y_local is not None
            else 0.0
        )
        raw_upperness_score = _normalize_range(float(roi_gray.shape[0]) - centroid_y, 0.0, float(roi_gray.shape[0]))
        upperness_score = float(raw_upperness_score)
        if transition_scoring_used and float(distance_from_stable) > 12.0:
            upperness_score = 0.0
        ellipse_score = _normalize_range(3.2 - ellipse_ratio, 0.0, 2.0)
        area_score = _normalize_range(220.0 - area, 0.0, 180.0)
        prior_y_score = _normalize_range(12.0 - float(distance_from_stable), 0.0, 12.0)
        source_bonus = 0.0
        if transition_scoring_used and candidate_source == "prior_band" and float(distance_from_stable) <= 12.0:
            source_bonus = 0.18
        if transition_scoring_used:
            base_score = (
                (0.20 * compactness)
                + (0.10 * ellipse_score)
                + (0.30 * proximity_score)
                + (0.20 * upperness_score)
                + (0.20 * prior_y_score)
                + source_bonus
            )
        else:
            base_score = (
                (0.30 * compactness)
                + (0.25 * ellipse_score)
                + (0.25 * proximity_score)
                + (0.10 * upperness_score)
                + (0.10 * area_score)
            )
        confidence = float(max(0.0, min(1.0, base_score * (1.0 - (0.35 * attached_support_score)))))
        candidates.append(
            {
                "confidence": confidence,
                "raw_x_local": float(roi["x0"] + centroid_x),
                "raw_y_local": float(roi["y0"] + centroid_y),
                "selected_roi_center_y_local": None if roi.get("center_y_local") is None else float(roi["center_y_local"]),
                "distance_from_stable_prior": float(distance_from_stable),
                "transition_scoring_used": bool(transition_scoring_used),
                "candidate_source": str(candidate_source),
                "prior_band_used": bool(candidate_source == "prior_band"),
                "upperness_score": float(upperness_score),
            }
        )

    for contour in whole_roi_contours:
        _append_candidate(contour, candidate_source="whole_roi")
    for contour in prior_band_contours:
        _append_candidate(contour, candidate_source="prior_band")

    if not candidates:
        return None
    deduped_candidates: list[dict] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            0 if item.get("candidate_source") == "prior_band" else 1,
            -float(item["confidence"]),
            float(item["distance_from_stable_prior"]),
            -float(item["raw_y_local"]),
        ),
    ):
        duplicate_index = None
        for index, existing in enumerate(deduped_candidates):
            if (
                abs(float(candidate["raw_y_local"]) - float(existing["raw_y_local"])) <= 3.0
                and abs(float(candidate["raw_x_local"]) - float(existing["raw_x_local"])) <= 6.0
            ):
                duplicate_index = index
                break
        if duplicate_index is None:
            deduped_candidates.append(candidate)
            continue
        existing = deduped_candidates[duplicate_index]
        existing_is_prior_band = bool(existing.get("candidate_source") == "prior_band")
        candidate_is_prior_band = bool(candidate.get("candidate_source") == "prior_band")
        if candidate_is_prior_band and not existing_is_prior_band:
            deduped_candidates[duplicate_index] = candidate
            continue
        if existing_is_prior_band and not candidate_is_prior_band:
            continue
        replacement_key = (
            -float(candidate["confidence"]),
            float(candidate["distance_from_stable_prior"]),
            -float(candidate["raw_y_local"]),
        )
        existing_key = (
            -float(existing["confidence"]),
            float(existing["distance_from_stable_prior"]),
            -float(existing["raw_y_local"]),
        )
        if replacement_key < existing_key:
            deduped_candidates[duplicate_index] = candidate
    candidates = deduped_candidates
    prior_band_candidate_count = int(
        sum(1 for candidate in candidates if candidate.get("candidate_source") == "prior_band")
    )
    lower_reflection_rejected = False
    far_from_prior_rejected = False
    if transition_scoring_used and stable_visible_line_y_local is not None:
        near_prior_candidates = [
            candidate
            for candidate in candidates
            if float(candidate["distance_from_stable_prior"]) <= 10.0
        ]
        if near_prior_candidates:
            best_near_prior = max(
                near_prior_candidates,
                key=lambda candidate: (
                    float(candidate["confidence"]),
                    -float(candidate["distance_from_stable_prior"]),
                    float(candidate["raw_y_local"]),
                ),
            )
            filtered_candidates = []
            for candidate in candidates:
                is_lower_reflection_like = bool(
                    float(candidate["raw_y_local"]) > float(stable_visible_line_y_local) + 25.0
                )
                if (
                    is_lower_reflection_like
                    and float(candidate["confidence"]) < float(best_near_prior["confidence"]) + 0.20
                ):
                    lower_reflection_rejected = True
                    continue
                filtered_candidates.append(candidate)
            if filtered_candidates:
                candidates = filtered_candidates
        near_prior_candidates = [
            candidate
            for candidate in candidates
            if float(candidate["distance_from_stable_prior"]) <= 12.0
        ]
        best_near_prior = None
        if near_prior_candidates:
            best_near_prior = max(
                near_prior_candidates,
                key=lambda candidate: (
                    float(candidate["confidence"]),
                    -float(candidate["distance_from_stable_prior"]),
                    bool(candidate.get("candidate_source") == "prior_band"),
                    float(candidate["raw_y_local"]),
                ),
            )
        filtered_candidates = []
        for candidate in candidates:
            distance_from_stable = float(candidate["distance_from_stable_prior"])
            far_from_prior = bool(distance_from_stable > 20.0)
            if not far_from_prior:
                filtered_candidates.append(candidate)
                continue
            has_supporting_prior_band = bool(candidate.get("candidate_source") == "prior_band")
            if best_near_prior is not None:
                if float(candidate["confidence"]) <= float(best_near_prior["confidence"]) + 0.25:
                    far_from_prior_rejected = True
                    continue
            elif not has_supporting_prior_band:
                far_from_prior_rejected = True
                continue
            filtered_candidates.append(candidate)
        candidates = filtered_candidates

    best = min(
        candidates,
        key=lambda candidate: (
            -float(candidate["confidence"]),
            float(candidate["distance_from_stable_prior"]),
            0 if candidate.get("candidate_source") == "prior_band" else 1,
            -float(candidate["raw_y_local"]),
        ),
    ) if candidates else None
    if best is None or float(best["confidence"]) < 0.25:
        return None

    payload = _candidate_payload(
        "only_nozzle",
        raw_x_local=float(best["raw_x_local"]),
        raw_y_local=float(best["raw_y_local"]),
        confidence=float(best["confidence"]),
        separation_y_local=float(best["raw_y_local"]),
        valley_score=float(best["confidence"]),
    )
    payload["selected_roi_center_y_local"] = best.get("selected_roi_center_y_local")
    payload["transition_scoring_used"] = bool(best.get("transition_scoring_used"))
    payload["distance_from_stable_prior"] = float(best.get("distance_from_stable_prior") or 0.0)
    payload["rejected_lower_reflection"] = bool(lower_reflection_rejected)
    payload["candidate_source"] = str(best.get("candidate_source") or "whole_roi")
    payload["prior_band_used"] = bool(best.get("candidate_source") == "prior_band")
    payload["prior_band_candidate_count"] = int(prior_band_candidate_count)
    payload["rejected_far_from_prior"] = bool(far_from_prior_rejected)
    return payload


def _detect_only_nozzle_candidate_v2(
    search_gray: np.ndarray,
    *,
    previous_x_local: float | None,
    previous_y_local: float | None,
    stable_visible_line_y_local: float | None,
    previous_tracked_y_local: float | None,
    attached_support_score: float,
):
    roi_centers_y_local = _only_nozzle_roi_center_candidates_v2(
        previous_y_local=previous_y_local,
        stable_visible_line_y_local=stable_visible_line_y_local,
        previous_tracked_y_local=previous_tracked_y_local,
    )
    best = None
    anchor_rejected_as_low_reflection = False
    for center_y_local in roi_centers_y_local:
        roi = _top_roi_bounds_v2(
            search_gray,
            previous_x_local=previous_x_local,
            previous_y_local=None if center_y_local is None else float(center_y_local),
        )
        roi["center_y_local"] = None if center_y_local is None else float(center_y_local)
        roi_gray = search_gray[roi["y0"] : roi["y1"], roi["x0"] : roi["x1"]]
        candidate = _detect_only_nozzle_candidate_in_roi_v2(
            roi_gray,
            roi=roi,
            previous_x_local=previous_x_local,
            stable_visible_line_y_local=stable_visible_line_y_local,
            attached_support_score=attached_support_score,
        )
        if candidate is None:
            continue
        if best is None:
            best = candidate
            continue
        candidate_key = (
            -float(candidate["confidence"]),
            abs(float(candidate["raw_y_local"]) - float(stable_visible_line_y_local)) if stable_visible_line_y_local is not None else 0.0,
            0 if candidate.get("candidate_source") == "prior_band" else 1,
            -float(candidate["raw_y_local"]),
        )
        best_key = (
            -float(best["confidence"]),
            abs(float(best["raw_y_local"]) - float(stable_visible_line_y_local)) if stable_visible_line_y_local is not None else 0.0,
            0 if best.get("candidate_source") == "prior_band" else 1,
            -float(best["raw_y_local"]),
        )
        if candidate_key < best_key:
            best = candidate

    if best is None:
        return None
    if bool(best.get("rejected_lower_reflection")):
        anchor_rejected_as_low_reflection = True
    best["roi_centers_y_local"] = [float(value) for value in roi_centers_y_local if value is not None]
    best["anchor_rejected_as_low_reflection"] = bool(anchor_rejected_as_low_reflection)
    return best


def _detect_attached_feature_bundle_v2(
    search_gray: np.ndarray,
    geometry: dict,
    profiles: dict,
    *,
    previous_attached_y_local: float | None,
    previous_mode_history: tuple[str, ...] | list[str] | None,
    stable_visible_line_y_local: float | None,
    provisional_visible_line_y_local: float | None = None,
    visible_line_streak_length: int,
    missing_visible_line_count: int,
    recent_attached_width_median_px: float | None,
    recent_attached_center_x_local: float | None,
):
    height = int(geometry["height"])
    if height <= 8:
        return {
            "candidates": {},
            "compact_droplet_score": 0.0,
            "neck_y_local": None,
            "neck_width_px": None,
            "neck_score": 0.0,
            "contour_completeness_score": 0.0,
            "contour_bilateral_row_fraction": 0.0,
            "contour_width_median_px": None,
            "contour_width_iqr_px": None,
            "contour_clipped_warning": False,
            "stable_visible_line_y_local": stable_visible_line_y_local,
            "visible_line_search_center_y_local": stable_visible_line_y_local,
            "visible_line_search_radius_px": None,
            "line_band_y_local": None,
            "line_band_score": 0.0,
            "late_widening_y_local": None,
            "late_widening_score": 0.0,
            "late_widening_used": False,
            "visible_line_band_top_y_local": None,
            "visible_line_band_bottom_y_local": None,
            "visible_line_band_height_px": None,
            "visible_line_span_width_px": None,
            "visible_line_span_fraction": None,
            "visible_line_dark_delta": None,
            "visible_line_vertical_overlap": None,
            "visible_line_used_hysteresis": False,
            "visible_line_used_relaxed_fallback": False,
            "visible_line_used_plateau_only_fallback": False,
            "visible_line_valid_late_band": False,
            "visible_line_plateau_mode": None,
            "plateau_suppressed_on_acquisition": False,
            "hollow_bulb_guard_active": False,
            "visible_line_rejected_by_hollow_bulb_guard": False,
            "visible_line_rejected_by_upper_cue_conflict": False,
            "visible_line_lower_peak_prior_constrained": False,
            "visible_line_effective_lower_peak_y_local": None,
            "visible_line_acquisition_search_center_y_local": None,
            "visible_line_acquisition_upper_bound_y_local": None,
            "bridge_suppressed_by_clipped_contour": False,
            "bridge_suppressed_by_plateau": False,
            "bridge_suppressed_by_prior_conflict": False,
            "late_bridge_delta_from_prior_px": None,
            "late_plateau_delta_from_prior_px": None,
            "visible_line_bridge_x0_local": None,
            "visible_line_bridge_x1_local": None,
            "late_plateau_band_top_y_local": None,
            "late_plateau_band_bottom_y_local": None,
            "late_plateau_picked_y_local": None,
            "only_nozzle_candidate_source": None,
            "only_nozzle_prior_band_used": False,
            "only_nozzle_prior_band_candidate_count": 0,
            "only_nozzle_rejected_far_from_prior": False,
            "only_nozzle_transition_scoring_used": False,
            "only_nozzle_distance_from_stable_prior_px": None,
            "only_nozzle_rejected_lower_reflection": False,
            "only_nozzle_anchor_rejected_as_low_reflection": False,
            "attached_support_score": 0.0,
        }

    droplet_metrics = _compact_droplet_metrics_v2(geometry)
    neck_metrics = _width_neck_metrics_v2(geometry, profiles)
    height_support = _normalize_range(float(height), 28.0, 150.0)
    width_support = _normalize_range(float(geometry["q90_width"]), 10.0, 75.0)
    base_attached_support_score = float(0.45 * height_support * width_support)
    line_metrics = _visible_line_metrics_v2(
        search_gray,
        geometry,
        profiles,
        neck_metrics=neck_metrics,
        compact_droplet_score=float(droplet_metrics["score"]),
        droplet_y_local=float(droplet_metrics["raw_y_local"]),
        previous_attached_y_local=previous_attached_y_local,
        previous_mode_history=previous_mode_history,
        stable_visible_line_y_local=stable_visible_line_y_local,
        provisional_visible_line_y_local=provisional_visible_line_y_local,
        visible_line_streak_length=int(visible_line_streak_length),
        missing_visible_line_count=int(missing_visible_line_count),
        attached_support_score=float(base_attached_support_score),
        recent_attached_width_median_px=recent_attached_width_median_px,
        recent_attached_center_x_local=recent_attached_center_x_local,
    )
    fallback_search_config = None
    fallback_contour_metrics = None
    if line_metrics is None:
        fallback_search_config, fallback_contour_metrics = _visible_line_context_v2(
            geometry,
            neck_metrics=neck_metrics,
            compact_droplet_score=float(droplet_metrics["score"]),
            droplet_y_local=float(droplet_metrics["raw_y_local"]),
            previous_attached_y_local=previous_attached_y_local,
            previous_mode_history=previous_mode_history,
            stable_visible_line_y_local=stable_visible_line_y_local,
            provisional_visible_line_y_local=provisional_visible_line_y_local,
            visible_line_streak_length=int(visible_line_streak_length),
            missing_visible_line_count=int(missing_visible_line_count),
            recent_attached_width_median_px=recent_attached_width_median_px,
            recent_attached_center_x_local=recent_attached_center_x_local,
        )

    max_width = max(1, int(geometry["max_width"]))
    aspect_ratio = float(height) / float(max_width)
    compact_droplet_score = float(droplet_metrics["score"])
    if not (height <= 120 or aspect_ratio <= 1.35):
        compact_droplet_score *= 0.65

    neck_score = 0.0 if neck_metrics is None else float(neck_metrics["score"])
    line_band_score = 0.0 if line_metrics is None else float(line_metrics["score"])
    attached_support_score = float(max(neck_score, line_band_score, base_attached_support_score))
    visible_line_rejected_by_upper_cue_conflict = False
    visible_line_acquisition_allowed = True
    if line_metrics is not None and stable_visible_line_y_local is None:
        line_y_local = float(line_metrics["raw_y_local"])
        provisional_conflict = bool(
            provisional_visible_line_y_local is not None
            and abs(float(line_y_local) - float(provisional_visible_line_y_local)) > 4.0
            and float(line_band_score) < 0.98
        )
        previous_attached_conflict = bool(
            provisional_visible_line_y_local is None
            and previous_attached_y_local is not None
            and (
                line_metrics.get("acquisition_upper_bound_y_local") in (None, "")
                or float(previous_attached_y_local) <= float(line_metrics.get("acquisition_upper_bound_y_local")) + 4.0
            )
            and abs(float(line_y_local) - float(previous_attached_y_local)) > 8.0
            and float(line_band_score) < 0.98
        )
        droplet_conflict = bool(
            float(compact_droplet_score) >= 0.55
            and droplet_metrics.get("raw_y_local") is not None
            and float(droplet_metrics["raw_y_local"]) <= (line_y_local - 12.0)
            and float(line_band_score) < float(MODE_SCORE_THRESHOLDS["visible_line_strong_override"])
            and abs(float(droplet_metrics["raw_y_local"]) - line_y_local) > 8.0
        )
        guard_reject = bool(
            line_metrics.get("rejected_by_hollow_bulb_guard")
            or line_metrics.get("acquisition_row_out_of_bounds")
        )
        visible_line_rejected_by_upper_cue_conflict = bool(
            droplet_conflict or provisional_conflict or previous_attached_conflict
        )
        visible_line_acquisition_allowed = not (guard_reject or visible_line_rejected_by_upper_cue_conflict)

    candidates = {
        "attached_black_droplet_center": _candidate_payload(
            "attached_black_droplet_center",
            raw_x_local=float(droplet_metrics["raw_x_local"]),
            raw_y_local=float(droplet_metrics["raw_y_local"]),
            confidence=float(max(0.0, min(1.0, compact_droplet_score))),
        )
    }
    if neck_metrics is not None:
        candidates["attached_core_separation"] = _candidate_payload(
            "attached_core_separation",
            raw_x_local=float(neck_metrics["raw_x_local"]),
            raw_y_local=float(neck_metrics["raw_y_local"]),
            confidence=float(neck_score),
            upper_peak_y_local=neck_metrics.get("upper_peak_y_local"),
            lower_peak_y_local=neck_metrics.get("lower_peak_y_local"),
            separation_y_local=neck_metrics.get("neck_y_local"),
            valley_score=float(neck_metrics.get("darkness") or 0.0),
        )
    if line_metrics is not None:
        visible_candidate = _candidate_payload(
            "visible_nozzle_line",
            raw_x_local=float(line_metrics["raw_x_local"]),
            raw_y_local=float(line_metrics["raw_y_local"]),
            confidence=float(line_band_score),
            upper_peak_y_local=line_metrics.get("upper_peak_y_local"),
            lower_peak_y_local=line_metrics.get("lower_peak_y_local"),
            separation_y_local=line_metrics.get("line_band_y_local"),
            valley_score=float(line_band_score),
        )
        visible_candidate["used_hysteresis"] = bool(line_metrics.get("used_hysteresis"))
        visible_candidate["bridge_x0_local"] = line_metrics.get("bridge_x0_local")
        visible_candidate["bridge_x1_local"] = line_metrics.get("bridge_x1_local")
        visible_candidate["span_fraction"] = line_metrics.get("span_fraction")
        visible_candidate["search_center_y_local"] = line_metrics.get("search_center_y_local")
        visible_candidate["search_radius_px"] = line_metrics.get("search_radius_px")
        visible_candidate["used_relaxed_fallback"] = bool(line_metrics.get("used_relaxed_fallback"))
        visible_candidate["late_widening_used"] = bool(line_metrics.get("late_widening_used"))
        if visible_line_acquisition_allowed:
            candidates["visible_nozzle_line"] = visible_candidate

    return {
        "candidates": candidates,
        "compact_droplet_score": float(compact_droplet_score),
        "neck_y_local": None if neck_metrics is None else float(neck_metrics["neck_y_local"]),
        "neck_width_px": None if neck_metrics is None else float(neck_metrics["neck_width_px"]),
        "neck_score": float(neck_score),
        "contour_completeness_score": (
            float(line_metrics.get("contour_completeness_score") or 0.0)
            if line_metrics is not None
            else (0.0 if fallback_contour_metrics is None else float(fallback_contour_metrics.get("completeness_score") or 0.0))
        ),
        "contour_bilateral_row_fraction": (
            float(line_metrics.get("contour_bilateral_row_fraction") or 0.0)
            if line_metrics is not None
            else (0.0 if fallback_contour_metrics is None else float(fallback_contour_metrics.get("bilateral_row_fraction") or 0.0))
        ),
        "contour_width_median_px": (
            line_metrics.get("contour_width_median_px")
            if line_metrics is not None
            else (None if fallback_contour_metrics is None else fallback_contour_metrics.get("width_median_px"))
        ),
        "contour_width_iqr_px": (
            line_metrics.get("contour_width_iqr_px")
            if line_metrics is not None
            else (None if fallback_contour_metrics is None else fallback_contour_metrics.get("width_iqr_px"))
        ),
        "contour_clipped_warning": (
            bool(line_metrics.get("contour_clipped_warning"))
            if line_metrics is not None
            else bool(fallback_contour_metrics is not None and fallback_contour_metrics.get("clipped_warning"))
        ),
        "stable_visible_line_y_local": None if stable_visible_line_y_local is None else float(stable_visible_line_y_local),
        "visible_line_search_center_y_local": (
            None
            if line_metrics is None and fallback_search_config is None
            else float(line_metrics["search_center_y_local"]) if line_metrics is not None else float(fallback_search_config["center_y_local"])
        ),
        "visible_line_search_radius_px": (
            None
            if line_metrics is None and fallback_search_config is None
            else int(line_metrics["search_radius_px"]) if line_metrics is not None else int(fallback_search_config["radius_px"])
        ),
        "line_band_y_local": None if line_metrics is None else float(line_metrics["line_band_y_local"]),
        "line_band_score": float(line_band_score),
        "late_widening_y_local": None if line_metrics is None else line_metrics.get("late_widening_y_local"),
        "late_widening_score": 0.0 if line_metrics is None or line_metrics.get("late_widening_score") is None else float(line_metrics["late_widening_score"]),
        "late_widening_used": False if line_metrics is None else bool(line_metrics.get("late_widening_used")),
        "late_plateau_band_top_y_local": None if line_metrics is None else line_metrics.get("late_plateau_band_top_y_local"),
        "late_plateau_band_bottom_y_local": None if line_metrics is None else line_metrics.get("late_plateau_band_bottom_y_local"),
        "late_plateau_picked_y_local": None if line_metrics is None else line_metrics.get("late_plateau_picked_y_local"),
        "visible_line_band_top_y_local": None
        if line_metrics is None or line_metrics.get("band_top_y_local") is None
        else float(line_metrics["band_top_y_local"]),
        "visible_line_band_bottom_y_local": None
        if line_metrics is None or line_metrics.get("band_bottom_y_local") is None
        else float(line_metrics["band_bottom_y_local"]),
        "visible_line_band_height_px": None
        if line_metrics is None or line_metrics.get("band_height_px") is None
        else int(line_metrics["band_height_px"]),
        "visible_line_span_width_px": None
        if line_metrics is None or line_metrics.get("span_width_px") is None
        else int(line_metrics["span_width_px"]),
        "visible_line_span_fraction": None
        if line_metrics is None or line_metrics.get("span_fraction") is None
        else float(line_metrics["span_fraction"]),
        "visible_line_dark_delta": None
        if line_metrics is None or line_metrics.get("dark_delta") is None
        else float(line_metrics["dark_delta"]),
        "visible_line_vertical_overlap": None
        if line_metrics is None or line_metrics.get("vertical_overlap") is None
        else float(line_metrics["vertical_overlap"]),
        "visible_line_used_hysteresis": False if line_metrics is None else bool(line_metrics["used_hysteresis"]),
        "visible_line_used_relaxed_fallback": False if line_metrics is None else bool(line_metrics["used_relaxed_fallback"]),
        "visible_line_used_plateau_only_fallback": False if line_metrics is None else bool(line_metrics.get("used_plateau_only_fallback")),
        "visible_line_valid_late_band": False if line_metrics is None else bool(line_metrics.get("valid_late_band")),
        "visible_line_plateau_mode": None if line_metrics is None else line_metrics.get("plateau_mode"),
        "plateau_suppressed_on_acquisition": False if line_metrics is None else bool(line_metrics.get("plateau_suppressed_on_acquisition")),
        "hollow_bulb_guard_active": False if line_metrics is None else bool(line_metrics.get("hollow_bulb_guard_active")),
        "visible_line_rejected_by_hollow_bulb_guard": False if line_metrics is None else bool(line_metrics.get("rejected_by_hollow_bulb_guard")),
        "visible_line_rejected_by_upper_cue_conflict": bool(visible_line_rejected_by_upper_cue_conflict),
        "visible_line_lower_peak_prior_constrained": False if line_metrics is None else bool(line_metrics.get("lower_peak_prior_constrained")),
        "visible_line_effective_lower_peak_y_local": None if line_metrics is None else line_metrics.get("effective_lower_peak_y_local"),
        "visible_line_acquisition_search_center_y_local": (
            None
            if line_metrics is None and fallback_search_config is None
            else (
                line_metrics.get("acquisition_search_center_y_local")
                if line_metrics is not None
                else fallback_search_config.get("acquisition_search_center_y_local")
            )
        ),
        "visible_line_acquisition_upper_bound_y_local": (
            None
            if line_metrics is None and fallback_search_config is None
            else (
                line_metrics.get("acquisition_upper_bound_y_local")
                if line_metrics is not None
                else fallback_search_config.get("acquisition_upper_bound_y_local")
            )
        ),
        "bridge_suppressed_by_clipped_contour": False if line_metrics is None else bool(line_metrics.get("bridge_suppressed_by_clipped_contour")),
        "bridge_suppressed_by_plateau": False if line_metrics is None else bool(line_metrics.get("bridge_suppressed_by_plateau")),
        "bridge_suppressed_by_prior_conflict": False if line_metrics is None else bool(line_metrics.get("bridge_suppressed_by_prior_conflict")),
        "late_bridge_delta_from_prior_px": None if line_metrics is None else line_metrics.get("bridge_delta_from_prior_px"),
        "late_plateau_delta_from_prior_px": None if line_metrics is None else line_metrics.get("plateau_delta_from_prior_px"),
        "visible_line_bridge_x0_local": None
        if line_metrics is None or line_metrics.get("bridge_x0_local") is None
        else float(line_metrics["bridge_x0_local"]),
        "visible_line_bridge_x1_local": None
        if line_metrics is None or line_metrics.get("bridge_x1_local") is None
        else float(line_metrics["bridge_x1_local"]),
        "only_nozzle_candidate_source": None,
        "only_nozzle_prior_band_used": False,
        "only_nozzle_prior_band_candidate_count": 0,
        "only_nozzle_rejected_far_from_prior": False,
        "only_nozzle_transition_scoring_used": False,
        "only_nozzle_distance_from_stable_prior_px": None,
        "only_nozzle_rejected_lower_reflection": False,
        "only_nozzle_anchor_rejected_as_low_reflection": False,
        "attached_support_score": float(attached_support_score),
    }


def _droplet_reflection_like_v2(
    *,
    droplet_y_local: float | None,
    stable_visible_line_y_local: float | None,
    attached_support_score: float,
    line_band_score: float,
):
    if droplet_y_local is None or stable_visible_line_y_local is None:
        return False
    return bool(
        float(attached_support_score) < float(MODE_SCORE_THRESHOLDS["attached_support_low"])
        and float(line_band_score) <= 0.0
        and float(droplet_y_local) < float(stable_visible_line_y_local) - 40.0
    )


def _choose_raw_detection_v2(
    candidates: dict[str, dict],
    *,
    compact_droplet_score: float,
    neck_score: float,
    line_band_score: float,
    only_nozzle_score: float,
    attached_support_score: float,
    stable_visible_line_y_local: float | None = None,
    only_nozzle_y_local: float | None = None,
    neck_y_local: float | None = None,
    droplet_y_local: float | None = None,
    line_candidate_used_hysteresis: bool = False,
    line_candidate_used_relaxed_fallback: bool = False,
    line_candidate_used_widening: bool = False,
    missing_visible_line_count: int = 0,
):
    thresholds = MODE_SCORE_THRESHOLDS
    line_enter = float(thresholds["visible_line_enter"])
    line_keep = float(thresholds["visible_line_keep"])
    strong_line = float(thresholds["visible_line_strong_override"])
    strong_core_threshold = max(float(thresholds["core"]), 0.50)
    strong_neck_threshold = 0.55
    only_nozzle = candidates.get("only_nozzle")
    visible_line = candidates.get("visible_nozzle_line")
    core = candidates.get("attached_core_separation")
    droplet = candidates.get("attached_black_droplet_center")
    stable_visible_exists = stable_visible_line_y_local is not None
    droplet_reflection_like = _droplet_reflection_like_v2(
        droplet_y_local=droplet_y_local,
        stable_visible_line_y_local=stable_visible_line_y_local,
        attached_support_score=attached_support_score,
        line_band_score=line_band_score,
    )
    visible_line_available = bool(
        visible_line is not None
        and line_band_score
        >= (
            line_keep
            if (line_candidate_used_hysteresis or line_candidate_used_relaxed_fallback or line_candidate_used_widening)
            else line_enter
        )
    )
    neck_within_prior = bool(
        stable_visible_line_y_local is None
        or neck_y_local is None
        or abs(float(neck_y_local) - float(stable_visible_line_y_local)) <= 8.0
    )

    if (
        only_nozzle is not None
        and only_nozzle_score >= float(thresholds["only_nozzle"])
        and attached_support_score < float(thresholds["attached_support_low"])
    ):
        return only_nozzle

    if (
        only_nozzle is not None
        and stable_visible_exists
        and only_nozzle_y_local is not None
        and attached_support_score < float(thresholds["attached_support_low"])
        and line_band_score <= 0.0
        and abs(float(only_nozzle_y_local) - float(stable_visible_line_y_local)) <= 10.0
    ):
        return only_nozzle

    if droplet_reflection_like:
        if only_nozzle is not None and only_nozzle_score >= 0.30:
            return only_nozzle
        droplet = None
        only_nozzle = None

    if stable_visible_exists and visible_line_available:
        return visible_line

    if (
        droplet is not None
        and compact_droplet_score >= float(thresholds["droplet"])
        and attached_support_score < 0.55
        and not stable_visible_exists
    ):
        line_override = bool(
            visible_line_available
            and line_band_score >= float(compact_droplet_score + thresholds["override_margin"])
        )
        core_override = bool(
            core is not None
            and neck_score >= max(float(strong_core_threshold), float(compact_droplet_score + thresholds["override_margin"]))
        )
        if not line_override and not core_override:
            return droplet

    if (
        visible_line_available
        and line_band_score >= float(line_enter)
    ):
        return visible_line

    droplet_can_hold = bool(
        droplet is not None
        and compact_droplet_score >= float(thresholds["droplet"])
        and not (
            stable_visible_exists
            and int(missing_visible_line_count) < 4
            and attached_support_score >= float(thresholds["attached_support_low"])
        )
        and not visible_line_available
        and (
            neck_score < strong_core_threshold
            or neck_score < float(compact_droplet_score + thresholds["override_margin"])
        )
        and attached_support_score < 0.55
    )
    if droplet_can_hold:
        return droplet

    if (
        core is not None
        and neck_score >= float(strong_core_threshold)
        and (not stable_visible_exists or neck_within_prior)
        and (
            not visible_line_available
            or line_band_score < strong_line
        )
        and (neck_y_local is None or neck_score >= strong_neck_threshold)
    ):
        return core

    if visible_line_available:
        return visible_line
    if droplet is not None:
        return droplet
    if only_nozzle is not None:
        return only_nozzle
    return None


def _detect_raw_nozzle(
    gray: np.ndarray,
    *,
    search_width_frac: float,
    search_top_frac: float,
    search_bottom_frac: float,
    blur_sigma: float,
    residual_scale: float,
    residual_threshold: int,
    min_area_px: int,
    top_band_slack_px: int,
    previous_nozzle_x_px: float | None = None,
    previous_nozzle_y_px: float | None = None,
    previous_attached_y_px: float | None = None,
    previous_mode_history: tuple[str, ...] | list[str] | None = None,
    stable_visible_line_y_px: float | None = None,
    provisional_visible_line_y_px: float | None = None,
    visible_line_streak_length: int = 0,
    missing_visible_line_count: int = 0,
    recent_attached_width_median_px: float | None = None,
    recent_attached_center_x_px: float | None = None,
):
    search = _search_bounds(
        gray.shape,
        search_width_frac=search_width_frac,
        search_top_frac=search_top_frac,
        search_bottom_frac=search_bottom_frac,
    )
    search_gray = gray[search["y0"] : search["y1"], search["x0"] : search["x1"]]
    residual = _local_contrast_residual(search_gray, blur_sigma=blur_sigma)
    residual_scaled, strong_mask, contour_mask, weak_mask, weak_connected_mask = _residual_masks_v2(
        residual,
        residual_scale=residual_scale,
        residual_threshold=residual_threshold,
        min_area_px=min_area_px,
    )
    components, labels = _component_rows(contour_mask)
    top_candidates = _select_top_candidates(
        components,
        search_width=search["width"],
        min_area_px=min_area_px,
        top_band_slack_px=top_band_slack_px,
    )
    primary_label = None if not top_candidates else int(top_candidates[0]["label"])
    raw_candidate_mask = _mask_for_label(labels, primary_label)
    stable_visible_line_y_local = None if stable_visible_line_y_px is None else float(stable_visible_line_y_px - search["y0"])
    provisional_visible_line_y_local = None if provisional_visible_line_y_px is None else float(provisional_visible_line_y_px - search["y0"])
    previous_attached_y_local = None if previous_attached_y_px is None else float(previous_attached_y_px - search["y0"])
    local_visible_search_prior_y_local = stable_visible_line_y_local
    if local_visible_search_prior_y_local is None:
        local_visible_search_prior_y_local = provisional_visible_line_y_local
    raw_candidate_mask = _augment_candidate_mask_with_local_weak_v2(
        raw_candidate_mask,
        weak_connected_mask,
        stable_visible_line_y_local=local_visible_search_prior_y_local,
        previous_attached_y_local=previous_attached_y_local,
    )
    candidate_mask, _filled_contour = _filled_component_mask(raw_candidate_mask)
    geometry = _component_geometry(candidate_mask)

    if geometry is None:
        return {
            "search": search,
            "search_gray": search_gray,
            "residual_scaled": residual_scaled,
            "mask": strong_mask,
            "strong_mask": strong_mask,
            "contour_mask": contour_mask,
            "weak_mask": weak_mask,
            "candidate_mask": candidate_mask,
            "components": components,
            "top_candidates": top_candidates,
            "geometry": None,
            "profiles": None,
            "candidates": {},
            "raw_x": None,
            "raw_y": None,
            "confidence": 0.0,
            "mode": "no_signal",
            "valley_score": 0.0,
            "candidate_mask_area_px": 0,
            "static_line_x_local": None,
            "static_line_y_local": None,
            "attached_component_centroid_x_local": None,
            "attached_component_centroid_y_local": None,
            "bright_core_upper_y_local": None,
            "bright_core_lower_y_local": None,
            "separation_band_y_local": None,
            "compact_droplet_score": 0.0,
            "neck_y_local": None,
            "neck_width_px": None,
            "neck_score": 0.0,
            "contour_completeness_score": 0.0,
            "contour_bilateral_row_fraction": 0.0,
            "contour_width_median_px": None,
            "contour_width_iqr_px": None,
            "contour_clipped_warning": False,
            "stable_visible_line_y_local": None,
            "visible_line_search_center_y_local": None,
            "visible_line_search_radius_px": None,
            "line_band_y_local": None,
            "line_band_score": 0.0,
            "late_widening_y_local": None,
            "late_widening_score": 0.0,
            "late_widening_used": False,
            "visible_line_band_top_y_local": None,
            "visible_line_band_bottom_y_local": None,
            "visible_line_band_height_px": None,
            "visible_line_span_width_px": None,
            "visible_line_span_fraction": None,
            "visible_line_dark_delta": None,
            "visible_line_vertical_overlap": None,
            "visible_line_used_hysteresis": False,
            "visible_line_used_relaxed_fallback": False,
            "visible_line_used_plateau_only_fallback": False,
            "visible_line_valid_late_band": False,
            "visible_line_plateau_mode": None,
            "plateau_suppressed_on_acquisition": False,
            "hollow_bulb_guard_active": False,
            "visible_line_rejected_by_hollow_bulb_guard": False,
            "visible_line_rejected_by_upper_cue_conflict": False,
            "visible_line_acquisition_search_center_y_local": None,
            "visible_line_acquisition_upper_bound_y_local": None,
            "bridge_suppressed_by_clipped_contour": False,
            "bridge_suppressed_by_plateau": False,
            "bridge_suppressed_by_prior_conflict": False,
            "late_bridge_delta_from_prior_px": None,
            "late_plateau_delta_from_prior_px": None,
            "visible_line_bridge_x0_local": None,
            "visible_line_bridge_x1_local": None,
            "only_nozzle_y_local": None,
            "only_nozzle_score": 0.0,
            "only_nozzle_roi_centers_y_local": None,
            "only_nozzle_selected_roi_center_y_local": None,
            "only_nozzle_candidate_source": None,
            "only_nozzle_prior_band_used": False,
            "only_nozzle_prior_band_candidate_count": 0,
            "only_nozzle_rejected_far_from_prior": False,
            "only_nozzle_transition_scoring_used": False,
            "only_nozzle_distance_from_stable_prior_px": None,
            "only_nozzle_rejected_lower_reflection": False,
            "only_nozzle_anchor_rejected_as_low_reflection": False,
            "droplet_suppressed_as_reflection": False,
            "attached_support_score": 0.0,
        }

    profiles = _row_profiles(search_gray, geometry)
    previous_x_local = None if previous_nozzle_x_px is None else float(previous_nozzle_x_px - search["x0"])
    previous_y_local = None if previous_nozzle_y_px is None else float(previous_nozzle_y_px - search["y0"])
    recent_attached_center_x_local = None if recent_attached_center_x_px is None else float(recent_attached_center_x_px - search["x0"])

    attached_bundle = _detect_attached_feature_bundle_v2(
        search_gray,
        geometry,
        profiles,
        previous_attached_y_local=previous_attached_y_local,
        previous_mode_history=previous_mode_history,
        stable_visible_line_y_local=stable_visible_line_y_local,
        provisional_visible_line_y_local=provisional_visible_line_y_local,
        visible_line_streak_length=int(visible_line_streak_length),
        missing_visible_line_count=int(missing_visible_line_count),
        recent_attached_width_median_px=recent_attached_width_median_px,
        recent_attached_center_x_local=recent_attached_center_x_local,
    )
    candidates = dict(attached_bundle["candidates"])
    only_nozzle_candidate = _detect_only_nozzle_candidate_v2(
        search_gray,
        previous_x_local=previous_x_local,
        previous_y_local=previous_y_local,
        stable_visible_line_y_local=attached_bundle["stable_visible_line_y_local"],
        previous_tracked_y_local=previous_attached_y_local,
        attached_support_score=float(attached_bundle["attached_support_score"]),
    )
    if only_nozzle_candidate is not None:
        candidates["only_nozzle"] = only_nozzle_candidate
    only_nozzle_score = 0.0 if only_nozzle_candidate is None else float(only_nozzle_candidate.get("confidence") or 0.0)
    droplet_candidate = candidates.get("attached_black_droplet_center")
    droplet_suppressed_as_reflection = _droplet_reflection_like_v2(
        droplet_y_local=(
            None
            if droplet_candidate is None
            else float(droplet_candidate.get("raw_y_local"))
        ),
        stable_visible_line_y_local=attached_bundle["stable_visible_line_y_local"],
        attached_support_score=float(attached_bundle["attached_support_score"]),
        line_band_score=float(attached_bundle["line_band_score"]),
    )
    detection = _choose_raw_detection_v2(
        candidates,
        compact_droplet_score=float(attached_bundle["compact_droplet_score"]),
        neck_score=float(attached_bundle["neck_score"]),
        line_band_score=float(attached_bundle["line_band_score"]),
        only_nozzle_score=float(only_nozzle_score),
        attached_support_score=float(attached_bundle["attached_support_score"]),
        stable_visible_line_y_local=attached_bundle["stable_visible_line_y_local"],
        only_nozzle_y_local=(
            None
            if only_nozzle_candidate is None
            else float(only_nozzle_candidate.get("raw_y_local"))
        ),
        neck_y_local=attached_bundle["neck_y_local"],
        droplet_y_local=(
            None
            if droplet_candidate is None
            else float(droplet_candidate.get("raw_y_local"))
        ),
        line_candidate_used_hysteresis=bool(attached_bundle["visible_line_used_hysteresis"]),
        line_candidate_used_relaxed_fallback=bool(attached_bundle["visible_line_used_relaxed_fallback"]),
        line_candidate_used_widening=bool(attached_bundle["late_widening_used"]),
        missing_visible_line_count=int(missing_visible_line_count),
    )

    raw_x = None
    raw_y = None
    mode = "no_signal"
    confidence = 0.0
    valley_score = 0.0
    bright_core_upper_y_local = None
    bright_core_lower_y_local = None
    separation_band_y_local = None
    if detection is not None:
        raw_x = float(search["x0"] + detection["raw_x_local"])
        raw_y = float(search["y0"] + detection["raw_y_local"])
        mode = str(detection["mode"])
        confidence = float(detection["confidence"])
        valley_score = float(detection.get("valley_score") or 0.0)
        if detection.get("upper_peak_y_local") is not None:
            bright_core_upper_y_local = float(detection["upper_peak_y_local"])
        if detection.get("lower_peak_y_local") is not None:
            bright_core_lower_y_local = float(detection["lower_peak_y_local"])
        if detection.get("separation_y_local") is not None:
            separation_band_y_local = float(detection["separation_y_local"])

    only_nozzle = candidates.get("only_nozzle")
    static_line_x_local = None if only_nozzle is None else float(only_nozzle["raw_x_local"])
    static_line_y_local = None if only_nozzle is None else float(only_nozzle["raw_y_local"])

    return {
        "search": search,
        "search_gray": search_gray,
        "residual_scaled": residual_scaled,
        "mask": strong_mask,
        "strong_mask": strong_mask,
        "contour_mask": contour_mask,
        "weak_mask": weak_mask,
        "candidate_mask": candidate_mask,
        "components": components,
        "top_candidates": top_candidates,
        "geometry": geometry,
        "profiles": profiles,
        "candidates": candidates,
        "raw_x": raw_x,
        "raw_y": raw_y,
        "confidence": confidence,
        "mode": mode,
        "valley_score": valley_score,
        "candidate_mask_area_px": int(np.count_nonzero(candidate_mask)),
        "static_line_x_local": static_line_x_local,
        "static_line_y_local": static_line_y_local,
        "attached_component_centroid_x_local": float(geometry["centroid_x"]),
        "attached_component_centroid_y_local": float(geometry["centroid_y"]),
        "bright_core_upper_y_local": bright_core_upper_y_local,
        "bright_core_lower_y_local": bright_core_lower_y_local,
        "separation_band_y_local": separation_band_y_local,
        "compact_droplet_score": float(attached_bundle["compact_droplet_score"]),
        "neck_y_local": attached_bundle["neck_y_local"],
        "neck_width_px": attached_bundle["neck_width_px"],
        "neck_score": float(attached_bundle["neck_score"]),
        "contour_completeness_score": float(attached_bundle["contour_completeness_score"]),
        "contour_bilateral_row_fraction": float(attached_bundle["contour_bilateral_row_fraction"]),
        "contour_width_median_px": attached_bundle["contour_width_median_px"],
        "contour_width_iqr_px": attached_bundle["contour_width_iqr_px"],
        "contour_clipped_warning": bool(attached_bundle["contour_clipped_warning"]),
        "stable_visible_line_y_local": attached_bundle["stable_visible_line_y_local"],
        "visible_line_search_center_y_local": attached_bundle["visible_line_search_center_y_local"],
        "visible_line_search_radius_px": attached_bundle["visible_line_search_radius_px"],
        "line_band_y_local": attached_bundle["line_band_y_local"],
        "line_band_score": float(attached_bundle["line_band_score"]),
        "late_widening_y_local": attached_bundle["late_widening_y_local"],
        "late_widening_score": float(attached_bundle["late_widening_score"]),
        "late_widening_used": bool(attached_bundle["late_widening_used"]),
        "visible_line_band_top_y_local": attached_bundle["visible_line_band_top_y_local"],
        "visible_line_band_bottom_y_local": attached_bundle["visible_line_band_bottom_y_local"],
        "visible_line_band_height_px": attached_bundle["visible_line_band_height_px"],
        "visible_line_span_width_px": attached_bundle["visible_line_span_width_px"],
        "visible_line_span_fraction": attached_bundle["visible_line_span_fraction"],
        "visible_line_dark_delta": attached_bundle["visible_line_dark_delta"],
        "visible_line_vertical_overlap": attached_bundle["visible_line_vertical_overlap"],
        "visible_line_used_hysteresis": bool(attached_bundle["visible_line_used_hysteresis"]),
        "visible_line_used_relaxed_fallback": bool(attached_bundle["visible_line_used_relaxed_fallback"]),
        "visible_line_used_plateau_only_fallback": bool(attached_bundle.get("visible_line_used_plateau_only_fallback")),
        "visible_line_valid_late_band": bool(attached_bundle.get("visible_line_valid_late_band")),
        "visible_line_plateau_mode": attached_bundle.get("visible_line_plateau_mode"),
        "plateau_suppressed_on_acquisition": bool(attached_bundle.get("plateau_suppressed_on_acquisition")),
        "hollow_bulb_guard_active": bool(attached_bundle.get("hollow_bulb_guard_active")),
        "visible_line_rejected_by_hollow_bulb_guard": bool(attached_bundle.get("visible_line_rejected_by_hollow_bulb_guard")),
        "visible_line_rejected_by_upper_cue_conflict": bool(attached_bundle.get("visible_line_rejected_by_upper_cue_conflict")),
        "bridge_suppressed_by_clipped_contour": bool(attached_bundle["bridge_suppressed_by_clipped_contour"]),
        "bridge_suppressed_by_plateau": bool(attached_bundle.get("bridge_suppressed_by_plateau")),
        "bridge_suppressed_by_prior_conflict": bool(attached_bundle.get("bridge_suppressed_by_prior_conflict")),
        "late_bridge_delta_from_prior_px": attached_bundle.get("late_bridge_delta_from_prior_px"),
        "late_plateau_delta_from_prior_px": attached_bundle.get("late_plateau_delta_from_prior_px"),
        "visible_line_acquisition_search_center_y_local": attached_bundle.get("visible_line_acquisition_search_center_y_local"),
        "visible_line_acquisition_upper_bound_y_local": attached_bundle.get("visible_line_acquisition_upper_bound_y_local"),
        "visible_line_bridge_x0_local": attached_bundle["visible_line_bridge_x0_local"],
        "visible_line_bridge_x1_local": attached_bundle["visible_line_bridge_x1_local"],
        "only_nozzle_y_local": None if only_nozzle is None else float(only_nozzle["raw_y_local"]),
        "only_nozzle_score": float(only_nozzle_score),
        "only_nozzle_roi_centers_y_local": None if only_nozzle is None else only_nozzle.get("roi_centers_y_local"),
        "only_nozzle_selected_roi_center_y_local": None if only_nozzle is None else only_nozzle.get("selected_roi_center_y_local"),
        "only_nozzle_candidate_source": None if only_nozzle is None else only_nozzle.get("candidate_source"),
        "only_nozzle_prior_band_used": False if only_nozzle is None else bool(only_nozzle.get("prior_band_used")),
        "only_nozzle_prior_band_candidate_count": 0 if only_nozzle is None else int(only_nozzle.get("prior_band_candidate_count") or 0),
        "only_nozzle_rejected_far_from_prior": False if only_nozzle is None else bool(only_nozzle.get("rejected_far_from_prior")),
        "only_nozzle_transition_scoring_used": False if only_nozzle is None else bool(only_nozzle.get("transition_scoring_used")),
        "only_nozzle_distance_from_stable_prior_px": None if only_nozzle is None else float(only_nozzle.get("distance_from_stable_prior") or 0.0),
        "only_nozzle_rejected_lower_reflection": False if only_nozzle is None else bool(only_nozzle.get("rejected_lower_reflection")),
        "only_nozzle_anchor_rejected_as_low_reflection": False if only_nozzle is None else bool(only_nozzle.get("anchor_rejected_as_low_reflection")),
        "droplet_suppressed_as_reflection": bool(droplet_suppressed_as_reflection),
        "attached_support_score": float(attached_bundle["attached_support_score"]),
    }


def _raw_mode_score(row: dict):
    raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
    if raw_mode == "only_nozzle":
        return float(row.get("only_nozzle_score") or row.get("raw_confidence") or 0.0)
    if raw_mode == "visible_nozzle_line":
        return float(row.get("line_band_score") or row.get("raw_confidence") or 0.0)
    if raw_mode == "attached_core_separation":
        return float(row.get("neck_score") or row.get("raw_confidence") or 0.0)
    if raw_mode == "attached_black_droplet_center":
        return float(row.get("compact_droplet_score") or row.get("raw_confidence") or 0.0)
    return float(row.get("raw_confidence") or 0.0)


def _mode_threshold_for_row(row: dict):
    raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
    if raw_mode == "only_nozzle":
        threshold = float(MODE_SCORE_THRESHOLDS["only_nozzle"])
        stable_visible_y = row.get("stable_visible_line_y_px")
        raw_y = row.get("raw_nozzle_y_px")
        attached_support_score = float(row.get("attached_support_score") or 0.0)
        if bool(row.get("droplet_suppressed_as_reflection")):
            threshold = min(threshold, 0.30)
        elif (
            stable_visible_y not in (None, "")
            and raw_y not in (None, "")
            and attached_support_score < float(MODE_SCORE_THRESHOLDS["attached_support_low"])
            and abs(float(raw_y) - float(stable_visible_y)) <= 8.0
        ):
            threshold = min(threshold, 0.30)
        return threshold
    if raw_mode == "visible_nozzle_line":
        if (
            bool(row.get("visible_line_used_hysteresis"))
            or bool(row.get("visible_line_used_relaxed_fallback"))
            or bool(row.get("late_widening_used"))
        ):
            return float(MODE_SCORE_THRESHOLDS["visible_line_keep"])
        return float(MODE_SCORE_THRESHOLDS["visible_line_enter"])
    if raw_mode == "attached_core_separation":
        return float(MODE_SCORE_THRESHOLDS["core"])
    if raw_mode == "attached_black_droplet_center":
        return float(MODE_SCORE_THRESHOLDS["droplet"])
    return 1.0


def _update_visible_line_state_v2(
    raw_row: dict,
    *,
    stable_visible_line_y_px: float | None,
    stable_visible_line_history: list[float],
    visible_line_streak_length: int,
    missing_visible_line_count: int,
    pending_visible_line_y_px: float | None,
    pending_visible_line_count: int,
    provisional_visible_line_y_px: float | None,
    provisional_visible_line_count: int,
    attached_support_low: float,
):
    raw_mode = _clean_text(raw_row.get("raw_mode")) or "no_signal"
    raw_score = _raw_mode_score(raw_row)
    mode_threshold = _mode_threshold_for_row(raw_row)
    attached_support_score = float(raw_row.get("attached_support_score") or 0.0)
    contour_completeness_score = float(raw_row.get("contour_completeness_score") or 0.0)
    bridge_suppressed_by_clipped_contour = bool(raw_row.get("bridge_suppressed_by_clipped_contour"))
    bridge_suppressed_by_plateau = bool(raw_row.get("bridge_suppressed_by_plateau"))
    bridge_suppressed_by_prior_conflict = bool(raw_row.get("bridge_suppressed_by_prior_conflict"))
    rejected_by_hollow_bulb_guard = bool(raw_row.get("visible_line_rejected_by_hollow_bulb_guard"))
    rejected_by_upper_cue_conflict = bool(raw_row.get("visible_line_rejected_by_upper_cue_conflict"))
    late_widening_y_px = raw_row.get("late_widening_y_px")
    late_widening_score = float(raw_row.get("late_widening_score") or 0.0)
    has_raw_point = raw_row.get("raw_nozzle_x_px") is not None and raw_row.get("raw_nozzle_y_px") is not None
    keep_raw = bool(has_raw_point and raw_score >= float(mode_threshold))
    attached_context = bool(raw_mode in ATTACHED_MODES or attached_support_score >= attached_support_low)
    used_relaxed_fallback = bool(raw_row.get("visible_line_used_relaxed_fallback"))
    used_plateau = bool(raw_row.get("late_widening_used"))

    if keep_raw and raw_mode == "visible_nozzle_line" and raw_row.get("raw_nozzle_y_px") is not None:
        candidate_y_px = float(raw_row["raw_nozzle_y_px"])
        visible_line_streak_length = int(visible_line_streak_length + 1)
        missing_visible_line_count = 0
        if stable_visible_line_y_px is None:
            if rejected_by_hollow_bulb_guard or rejected_by_upper_cue_conflict:
                if provisional_visible_line_y_px is None:
                    provisional_visible_line_count = 0
                else:
                    missing_visible_line_count = int(min(3, missing_visible_line_count + 1))
            elif provisional_visible_line_y_px is not None and abs(float(candidate_y_px) - float(provisional_visible_line_y_px)) <= 4.0:
                provisional_visible_line_count = int(provisional_visible_line_count + 1)
                provisional_visible_line_y_px = float(np.median(np.array([float(provisional_visible_line_y_px), float(candidate_y_px)], dtype=np.float32)))
                if int(provisional_visible_line_count) >= 2:
                    stable_visible_line_history = [float(provisional_visible_line_y_px)]
                    stable_visible_line_y_px = float(provisional_visible_line_y_px)
                    provisional_visible_line_y_px = None
                    provisional_visible_line_count = 0
                    missing_visible_line_count = 0
            elif provisional_visible_line_y_px is not None and abs(float(candidate_y_px) - float(provisional_visible_line_y_px)) > 4.0:
                missing_visible_line_count = int(min(3, missing_visible_line_count + 1))
                if missing_visible_line_count >= 3:
                    provisional_visible_line_y_px = None
                    provisional_visible_line_count = 0
                    missing_visible_line_count = 0
            else:
                provisional_visible_line_y_px = float(candidate_y_px)
                provisional_visible_line_count = 1
                missing_visible_line_count = 0
            pending_visible_line_y_px = None
            pending_visible_line_count = 0
        elif not used_relaxed_fallback and not used_plateau and not bridge_suppressed_by_prior_conflict:
            if stable_visible_line_y_px is None or abs(float(candidate_y_px) - float(stable_visible_line_y_px)) <= 6.0:
                stable_visible_line_history.append(float(candidate_y_px))
                stable_visible_line_history = stable_visible_line_history[-3:]
                stable_visible_line_y_px = float(np.median(np.array(stable_visible_line_history, dtype=np.float32)))
                pending_visible_line_y_px = None
                pending_visible_line_count = 0
            elif (
                abs(float(candidate_y_px) - float(stable_visible_line_y_px)) <= 12.0
                and raw_score >= float(MODE_SCORE_THRESHOLDS["visible_line_strong_override"])
                and not bridge_suppressed_by_clipped_contour
                and not bridge_suppressed_by_plateau
                and not bridge_suppressed_by_prior_conflict
                and (
                    float(candidate_y_px) >= float(stable_visible_line_y_px) - 6.0
                    or (
                        contour_completeness_score >= 0.70
                        and (
                            late_widening_y_px in (None, "")
                            or (
                                abs(float(candidate_y_px) - float(late_widening_y_px)) <= 4.0
                                and late_widening_score < raw_score
                            )
                        )
                    )
                )
            ):
                if pending_visible_line_y_px is not None and abs(float(candidate_y_px) - float(pending_visible_line_y_px)) <= 3.0:
                    pending_visible_line_count = int(pending_visible_line_count + 1)
                else:
                    pending_visible_line_y_px = float(candidate_y_px)
                    pending_visible_line_count = 1
                if int(pending_visible_line_count) >= 2:
                    stable_visible_line_history = [float(candidate_y_px)]
                    stable_visible_line_y_px = float(candidate_y_px)
                    pending_visible_line_y_px = None
                    pending_visible_line_count = 0
            else:
                pending_visible_line_y_px = None
                pending_visible_line_count = 0
            provisional_visible_line_y_px = None
            provisional_visible_line_count = 0
    elif keep_raw and raw_mode in DETACHED_MODES:
        raw_y_px = raw_row.get("raw_nozzle_y_px")
        preserve_visible_prior = bool(
            stable_visible_line_y_px is not None
            and raw_y_px not in (None, "")
            and attached_support_score < attached_support_low
            and abs(float(raw_y_px) - float(stable_visible_line_y_px)) <= 8.0
        )
        if preserve_visible_prior:
            visible_line_streak_length = 0
            missing_visible_line_count = int(min(4, missing_visible_line_count + 1))
            pending_visible_line_y_px = None
            pending_visible_line_count = 0
            if missing_visible_line_count >= 4:
                stable_visible_line_history = []
                stable_visible_line_y_px = None
                missing_visible_line_count = 0
        else:
            stable_visible_line_history = []
            stable_visible_line_y_px = None
            visible_line_streak_length = 0
            missing_visible_line_count = 0
            pending_visible_line_y_px = None
            pending_visible_line_count = 0
            provisional_visible_line_y_px = None
            provisional_visible_line_count = 0
    else:
        if stable_visible_line_y_px is not None and attached_context:
            missing_visible_line_count = int(min(4, missing_visible_line_count + 1))
            visible_line_streak_length = 0
            if missing_visible_line_count >= 4:
                stable_visible_line_history = []
                stable_visible_line_y_px = None
                missing_visible_line_count = 0
                pending_visible_line_y_px = None
                pending_visible_line_count = 0
                provisional_visible_line_y_px = None
                provisional_visible_line_count = 0
        elif stable_visible_line_y_px is None and provisional_visible_line_y_px is not None and attached_context:
            raw_y_px = raw_row.get("raw_nozzle_y_px")
            if (
                has_raw_point
                and raw_mode in {"attached_black_droplet_center", "attached_core_separation"}
                and raw_score >= 0.20
                and raw_y_px not in (None, "")
                and abs(float(raw_y_px) - float(provisional_visible_line_y_px)) <= 4.0
            ):
                confirmed_y_px = float(
                    np.median(
                        np.array(
                            [
                                float(provisional_visible_line_y_px),
                                float(raw_y_px),
                            ],
                            dtype=np.float32,
                        )
                    )
                )
                stable_visible_line_history = [confirmed_y_px]
                stable_visible_line_y_px = confirmed_y_px
                provisional_visible_line_y_px = None
                provisional_visible_line_count = 0
                missing_visible_line_count = 0
                pending_visible_line_y_px = None
                pending_visible_line_count = 0
                visible_line_streak_length = 0
            else:
                visible_line_streak_length = 0
                missing_visible_line_count = int(min(3, missing_visible_line_count + 1))
                pending_visible_line_y_px = None
                pending_visible_line_count = 0
                if missing_visible_line_count >= 3:
                    provisional_visible_line_y_px = None
                    provisional_visible_line_count = 0
                    missing_visible_line_count = 0
        elif stable_visible_line_y_px is None:
            visible_line_streak_length = 0
            missing_visible_line_count = 0
            provisional_visible_line_y_px = None
            provisional_visible_line_count = 0
        elif not attached_context:
            visible_line_streak_length = 0
            missing_visible_line_count = 0
            pending_visible_line_y_px = None
            pending_visible_line_count = 0
            provisional_visible_line_y_px = None
            provisional_visible_line_count = 0

    return {
        "stable_visible_line_y_px": stable_visible_line_y_px,
        "stable_visible_line_history": list(stable_visible_line_history),
        "visible_line_streak_length": int(visible_line_streak_length),
        "missing_visible_line_count": int(missing_visible_line_count),
        "pending_visible_line_y_px": pending_visible_line_y_px,
        "pending_visible_line_count": int(pending_visible_line_count),
        "provisional_visible_line_y_px": provisional_visible_line_y_px,
        "provisional_visible_line_count": int(provisional_visible_line_count),
        "keep_raw": bool(keep_raw),
        "attached_context": bool(attached_context),
    }


def _detect_run_raw_rows(
    run_id: str,
    frame_rows: list[dict],
    *,
    search_width_frac: float,
    search_top_frac: float,
    search_bottom_frac: float,
    blur_sigma: float,
    residual_scale: float,
    residual_threshold: int,
    min_area_px: int,
    top_band_slack_px: int,
):
    raw_rows = []
    frame_diagnostics = []
    previous_nozzle_x_px = None
    previous_nozzle_y_px = None
    previous_attached_y_px = None
    previous_mode_history: list[str] = []
    stable_visible_line_y_px = None
    visible_line_streak_length = 0
    missing_visible_line_count = 0
    stable_visible_line_history: list[float] = []
    pending_visible_line_y_px = None
    pending_visible_line_count = 0
    provisional_visible_line_y_px = None
    provisional_visible_line_count = 0
    recent_attached_width_history: list[float] = []
    recent_attached_center_history: list[float] = []
    attached_support_low = float(MODE_SCORE_THRESHOLDS["attached_support_low"])

    for frame_row in frame_rows:
        image_path = Path(str(frame_row["image_abs_path"]))
        gray = _load_gray_image(image_path)
        diagnostics = _detect_raw_nozzle(
            gray,
            search_width_frac=search_width_frac,
            search_top_frac=search_top_frac,
            search_bottom_frac=search_bottom_frac,
            blur_sigma=blur_sigma,
            residual_scale=residual_scale,
            residual_threshold=residual_threshold,
            min_area_px=min_area_px,
            top_band_slack_px=top_band_slack_px,
            previous_nozzle_x_px=previous_nozzle_x_px,
            previous_nozzle_y_px=previous_nozzle_y_px,
            previous_attached_y_px=previous_attached_y_px,
            previous_mode_history=tuple(previous_mode_history[-3:]),
            stable_visible_line_y_px=stable_visible_line_y_px,
            provisional_visible_line_y_px=provisional_visible_line_y_px,
            visible_line_streak_length=int(visible_line_streak_length),
            missing_visible_line_count=int(missing_visible_line_count),
            recent_attached_width_median_px=(
                None
                if not recent_attached_width_history
                else float(np.median(np.array(recent_attached_width_history, dtype=np.float32)))
            ),
            recent_attached_center_x_px=(
                None
                if not recent_attached_center_history
                else float(np.median(np.array(recent_attached_center_history, dtype=np.float32)))
            ),
        )
        raw_row = _raw_track_row(run_id, frame_row, diagnostics)
        state_update = _update_visible_line_state_v2(
            raw_row,
            stable_visible_line_y_px=stable_visible_line_y_px,
            stable_visible_line_history=stable_visible_line_history,
            visible_line_streak_length=visible_line_streak_length,
            missing_visible_line_count=missing_visible_line_count,
            pending_visible_line_y_px=pending_visible_line_y_px,
            pending_visible_line_count=pending_visible_line_count,
            provisional_visible_line_y_px=provisional_visible_line_y_px,
            provisional_visible_line_count=provisional_visible_line_count,
            attached_support_low=attached_support_low,
        )
        stable_visible_line_y_px = state_update["stable_visible_line_y_px"]
        stable_visible_line_history = list(state_update["stable_visible_line_history"])
        visible_line_streak_length = int(state_update["visible_line_streak_length"])
        missing_visible_line_count = int(state_update["missing_visible_line_count"])
        pending_visible_line_y_px = state_update["pending_visible_line_y_px"]
        pending_visible_line_count = int(state_update["pending_visible_line_count"])
        provisional_visible_line_y_px = state_update["provisional_visible_line_y_px"]
        provisional_visible_line_count = int(state_update["provisional_visible_line_count"])
        keep_raw = bool(state_update["keep_raw"])

        raw_row["stable_visible_line_y_px"] = stable_visible_line_y_px
        raw_row["pending_visible_line_y_px"] = pending_visible_line_y_px
        raw_row["provisional_visible_line_y_px"] = provisional_visible_line_y_px
        raw_row["provisional_visible_line_count"] = provisional_visible_line_count
        raw_rows.append(raw_row)
        frame_diagnostics.append(diagnostics)

        if raw_row.get("raw_nozzle_x_px") is not None and raw_row.get("raw_nozzle_y_px") is not None:
            previous_nozzle_x_px = float(raw_row["raw_nozzle_x_px"])
            previous_nozzle_y_px = float(raw_row["raw_nozzle_y_px"])
        raw_mode = _clean_text(raw_row.get("raw_mode")) or "no_signal"
        if keep_raw and raw_mode in ATTACHED_MODES and raw_row.get("raw_nozzle_y_px") is not None:
            previous_attached_y_px = float(raw_row["raw_nozzle_y_px"])
            if raw_row.get("contour_width_median_px") is not None:
                recent_attached_width_history.append(float(raw_row["contour_width_median_px"]))
                recent_attached_width_history = recent_attached_width_history[-3:]
            if raw_row.get("raw_nozzle_x_px") is not None:
                recent_attached_center_history.append(float(raw_row["raw_nozzle_x_px"]))
                recent_attached_center_history = recent_attached_center_history[-3:]
        if raw_row.get("raw_mode"):
            previous_mode_history.append(str(raw_row["raw_mode"]))

    return raw_rows, frame_diagnostics


def _row_mode_family(row: dict):
    raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
    if raw_mode in ATTACHED_MODES:
        return "attached"
    if raw_mode in DETACHED_MODES:
        return "detached"
    return "unknown"


def _is_stable_shift_anchor(row: dict, confidence_threshold: float):
    raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
    raw_confidence = _raw_mode_score(row)
    if row.get("raw_nozzle_x_px") is None or row.get("raw_nozzle_y_px") is None:
        return False
    if raw_mode == "only_nozzle":
        return raw_confidence >= float(MODE_SCORE_THRESHOLDS["only_nozzle"])
    if raw_mode in {"attached_core_separation", "visible_nozzle_line"}:
        return raw_confidence >= max(float(confidence_threshold), _mode_threshold_for_row(row))
    return False


def _merge_shift_boundaries(boundaries: list[dict], *, gap_frames: int):
    if not boundaries:
        return []
    merged = [dict(boundaries[0])]
    for boundary in boundaries[1:]:
        previous = merged[-1]
        if int(boundary["boundary_index"]) - int(previous["boundary_index"]) > int(gap_frames):
            merged.append(dict(boundary))
            continue
        if float(boundary["trigger_delta_px"]) > float(previous["trigger_delta_px"]):
            merged[-1] = dict(boundary)
    return merged


def _shift_boundaries(raw_rows: list[dict], *, shift_threshold_px: float, confidence_threshold: float):
    boundaries = []
    for index in range(3, len(raw_rows) - 2):
        previous_rows = [
            row
            for row in raw_rows[max(0, index - 3) : index]
            if _is_stable_shift_anchor(row, confidence_threshold)
        ]
        next_rows = [
            row
            for row in raw_rows[index : min(len(raw_rows), index + 3)]
            if _is_stable_shift_anchor(row, confidence_threshold)
        ]
        if len(previous_rows) < 2 or len(next_rows) < 2:
            continue

        prev_x = float(np.median([row["raw_nozzle_x_px"] for row in previous_rows]))
        prev_y = float(np.median([row["raw_nozzle_y_px"] for row in previous_rows]))
        next_x = float(np.median([row["raw_nozzle_x_px"] for row in next_rows]))
        next_y = float(np.median([row["raw_nozzle_y_px"] for row in next_rows]))
        delta = max(abs(next_x - prev_x), abs(next_y - prev_y))
        if delta < float(shift_threshold_px):
            continue
        boundaries.append(
            {
                "boundary_index": int(index + 1),
                "previous_capture_index": _int_or_none(previous_rows[-1]["capture_index"]),
                "next_capture_index": _int_or_none(next_rows[0]["capture_index"]),
                "median_dx_px": float(next_x - prev_x),
                "median_dy_px": float(next_y - prev_y),
                "trigger_delta_px": float(delta),
            }
        )
    return _merge_shift_boundaries(boundaries, gap_frames=5)


def _segment_for_frame(frame_index_1based: int, boundaries: list[dict]):
    segment_id = 1
    for boundary in boundaries:
        if int(frame_index_1based) >= int(boundary["boundary_index"]):
            segment_id += 1
    return int(segment_id)


def _reflection_like_anchor_row(row: dict, *, attached_support_low: float):
    raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
    if raw_mode != "attached_black_droplet_center":
        return False
    raw_y = row.get("raw_nozzle_y_px")
    stable_visible_y = row.get("stable_visible_line_y_px")
    if raw_y in (None, "") or stable_visible_y in (None, ""):
        return False
    attached_support_score = float(row.get("attached_support_score") or 0.0)
    return bool(
        attached_support_score < float(attached_support_low)
        and float(raw_y) < float(stable_visible_y) - 40.0
    )


def _provisional_visible_line_anchor_row(row: dict):
    raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
    if raw_mode != "visible_nozzle_line":
        return False
    return bool(
        (row.get("provisional_visible_line_y_px") not in (None, ""))
        and not (row.get("stable_visible_line_y_px") not in (None, ""))
    )


def _segment_anchors(rows: list[dict], *, segment_id: int, family: str, confidence_threshold: float):
    anchors = []
    rejected_reflection = False
    attached_support_low = float(MODE_SCORE_THRESHOLDS["attached_support_low"])
    for row in rows:
        if int(row["segment_id"]) != int(segment_id):
            continue
        if row.get("raw_nozzle_x_px") is None or row.get("raw_nozzle_y_px") is None:
            continue
        if _reflection_like_anchor_row(row, attached_support_low=attached_support_low):
            rejected_reflection = True
            continue
        if _provisional_visible_line_anchor_row(row):
            continue
        raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
        raw_confidence = _raw_mode_score(row)
        if family == "detached":
            if raw_mode == "only_nozzle" and raw_confidence >= float(MODE_SCORE_THRESHOLDS["only_nozzle"]):
                anchors.append(row)
        elif family == "attached":
            if raw_mode in {"attached_core_separation", "visible_nozzle_line"} and raw_confidence >= max(float(confidence_threshold), _mode_threshold_for_row(row)):
                anchors.append(row)
        else:
            if raw_confidence >= max(float(confidence_threshold), _mode_threshold_for_row(row)):
                anchors.append(row)
    return anchors, rejected_reflection


def _nearest_anchor_value(rows: list[dict], *, center_index: int, segment_id: int, family: str, confidence_threshold: float):
    anchors, rejected_reflection = _segment_anchors(
        rows,
        segment_id=segment_id,
        family=family,
        confidence_threshold=confidence_threshold,
    )
    if not anchors:
        return None, None, None, rejected_reflection

    capture_index = int(rows[center_index]["capture_index"])
    ordered = sorted(
        anchors,
        key=lambda row: (
            abs(int(row["capture_index"]) - capture_index),
            -float(row["raw_confidence"]),
        ),
    )
    chosen = ordered[0]
    return float(chosen["raw_nozzle_x_px"]), float(chosen["raw_nozzle_y_px"]), chosen, rejected_reflection


def _apply_tracking(
    raw_rows: list[dict],
    *,
    shift_threshold_px: float,
    confidence_threshold: float,
):
    boundaries = _shift_boundaries(
        raw_rows,
        shift_threshold_px=shift_threshold_px,
        confidence_threshold=confidence_threshold,
    )
    boundary_lookup = {int(boundary["boundary_index"]): boundary for boundary in boundaries}

    for row in raw_rows:
        capture_index = _int_or_none(row["capture_index"]) or 0
        row["segment_id"] = _segment_for_frame(capture_index, boundaries)
        row["shift_event_before"] = bool(capture_index in boundary_lookup)

    global_attached = [
        row
        for row in raw_rows
        if row.get("raw_nozzle_x_px") is not None
        and (_clean_text(row.get("raw_mode")) in {"attached_core_separation", "visible_nozzle_line"})
        and not _provisional_visible_line_anchor_row(row)
    ]
    global_detached = [
        row
        for row in raw_rows
        if row.get("raw_nozzle_x_px") is not None and (_row_mode_family(row) == "detached")
    ]

    final_rows = []
    last_tracked_by_family: dict[str, tuple[float, float]] = {}
    recent_raw_modes: list[str] = []
    attached_support_low = float(MODE_SCORE_THRESHOLDS["attached_support_low"])
    protected_visible_fill_count = 0
    transition_fill_count = 0
    for index, row in enumerate(raw_rows):
        raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
        raw_confidence = float(row.get("raw_confidence") or 0.0)
        raw_score = _raw_mode_score(row)
        mode_threshold = _mode_threshold_for_row(row)
        family = _row_mode_family(row)
        segment_id = int(row["segment_id"])
        attached_support_score = float(row.get("attached_support_score") or 0.0)
        stable_visible_prior_y = row.get("stable_visible_line_y_px")
        mode_tail = _mode_history_tail(recent_raw_modes, length=3)
        recent_visible_regime = bool(mode_tail and mode_tail.count("visible_nozzle_line") >= 2)
        recent_transition_regime = bool(
            mode_tail
            and sum(1 for mode_name in mode_tail if mode_name in {"visible_nozzle_line", "only_nozzle"}) >= 2
        )
        anchor_x, anchor_y, anchor_row, anchor_rejected_as_reflection = _nearest_anchor_value(
            raw_rows,
            center_index=index,
            segment_id=segment_id,
            family=family,
            confidence_threshold=confidence_threshold,
        )

        keep_raw = bool(row.get("raw_nozzle_x_px") is not None and row.get("raw_nozzle_y_px") is not None)
        if keep_raw:
            keep_raw = raw_score >= float(mode_threshold)
        if raw_mode in {"attached_core_separation", "visible_nozzle_line"}:
            if keep_raw and anchor_y is not None and raw_score < max(float(mode_threshold) + 0.18, 0.80):
                if abs(float(row["raw_nozzle_y_px"]) - float(anchor_y)) > 28.0:
                    keep_raw = False
        if raw_mode not in ATTACHED_MODES and raw_mode not in DETACHED_MODES:
            keep_raw = False

        tracked_x = None
        tracked_y = None
        used_segment_fill = False
        final_mode = raw_mode
        tracked_confidence = raw_confidence
        transition_fill_used = False
        transition_fill_source = None

        if keep_raw:
            tracked_x = float(row["raw_nozzle_x_px"])
            tracked_y = float(row["raw_nozzle_y_px"])
            if (
                family == "attached"
                and not bool(row.get("shift_event_before"))
                and "attached" in last_tracked_by_family
            ):
                _last_x, last_y = last_tracked_by_family["attached"]
                delta_y = float(tracked_y - last_y)
                if abs(delta_y) > 12.0:
                    tracked_y = float(last_y + (12.0 * np.sign(delta_y)))
            protected_visible_fill_count = 0
            transition_fill_count = 0
        else:
            used_visible_prior_fill = False
            used_transition_fill = False
            if (
                family == "attached"
                and stable_visible_prior_y is not None
                and attached_support_score >= attached_support_low
                and recent_visible_regime
                and protected_visible_fill_count < 3
            ):
                tracked_y = float(stable_visible_prior_y)
                if row.get("raw_nozzle_x_px") is not None:
                    tracked_x = float(row["raw_nozzle_x_px"])
                elif "attached" in last_tracked_by_family:
                    tracked_x = float(last_tracked_by_family["attached"][0])
                used_visible_prior_fill = tracked_x is not None and tracked_y is not None
                if used_visible_prior_fill:
                    protected_visible_fill_count = int(protected_visible_fill_count + 1)
                    transition_fill_source = "stable_visible_line_prior"
            if not used_visible_prior_fill:
                protected_visible_fill_count = 0
                if (
                    raw_mode == "no_signal"
                    and stable_visible_prior_y is not None
                    and recent_transition_regime
                    and transition_fill_count < 3
                ):
                    tracked_y = float(stable_visible_prior_y)
                    if row.get("raw_nozzle_x_px") is not None:
                        tracked_x = float(row["raw_nozzle_x_px"])
                    elif "detached" in last_tracked_by_family:
                        tracked_x = float(last_tracked_by_family["detached"][0])
                    elif "attached" in last_tracked_by_family:
                        tracked_x = float(last_tracked_by_family["attached"][0])
                    used_transition_fill = tracked_x is not None and tracked_y is not None
                    if used_transition_fill:
                        transition_fill_count = int(transition_fill_count + 1)
                        transition_fill_used = True
                        transition_fill_source = "stable_visible_line_prior"
                if not used_transition_fill:
                    transition_fill_count = 0
                    if (
                        family == "attached"
                        and stable_visible_prior_y in (None, "")
                        and raw_mode in {"attached_black_droplet_center", "attached_core_separation"}
                        and row.get("raw_nozzle_x_px") is not None
                        and row.get("raw_nozzle_y_px") is not None
                    ):
                        tracked_x = float(row["raw_nozzle_x_px"])
                        tracked_y = float(row["raw_nozzle_y_px"])
                        transition_fill_source = "local_raw_fallback"
                    else:
                        tracked_x, tracked_y = anchor_x, anchor_y
                        if tracked_x is not None and tracked_y is not None:
                            transition_fill_source = (
                                "only_nozzle_anchor"
                                if anchor_row is not None and (_clean_text(anchor_row.get("raw_mode")) == "only_nozzle")
                                else "generic_anchor"
                            )
            if tracked_x is None or tracked_y is None:
                fallback = global_detached if family == "detached" else global_attached
                if fallback:
                    ordered = sorted(
                        fallback,
                        key=lambda candidate: (
                            abs(int(candidate["capture_index"]) - int(row["capture_index"])),
                            -float(candidate.get("raw_confidence") or 0.0),
                        ),
                    )
                    tracked_x = float(ordered[0]["raw_nozzle_x_px"])
                    tracked_y = float(ordered[0]["raw_nozzle_y_px"])
                    if transition_fill_source is None:
                        transition_fill_source = "global_fallback"
            if tracked_x is None or tracked_y is None:
                if row.get("raw_nozzle_x_px") is not None and row.get("raw_nozzle_y_px") is not None:
                    tracked_x = float(row["raw_nozzle_x_px"])
                    tracked_y = float(row["raw_nozzle_y_px"])
            used_segment_fill = tracked_x is not None and tracked_y is not None
            if used_visible_prior_fill or used_transition_fill:
                tracked_confidence = max(0.22, raw_confidence * 0.72 if raw_confidence > 0.0 else 0.30)
            else:
                tracked_confidence = max(0.18, raw_confidence * 0.65 if raw_confidence > 0.0 else 0.25)
            final_mode = "segment_fill" if used_segment_fill else raw_mode

        final_row = dict(row)
        final_row["tracked_nozzle_x_px"] = tracked_x
        final_row["tracked_nozzle_y_px"] = tracked_y
        final_row["tracked_confidence"] = float(min(1.0, tracked_confidence))
        final_row["filled_from_segment"] = bool(used_segment_fill)
        final_row["used_segment_fill"] = bool(used_segment_fill)
        final_row["final_mode"] = final_mode
        final_row["detection_mode"] = final_mode
        final_row["transition_fill_used"] = bool(transition_fill_used)
        final_row["transition_fill_source"] = transition_fill_source
        final_row["anchor_rejected_as_reflection"] = bool(anchor_rejected_as_reflection)
        final_rows.append(final_row)
        if tracked_x is not None and tracked_y is not None and family in {"attached", "detached"}:
            last_tracked_by_family[family] = (float(tracked_x), float(tracked_y))
        recent_raw_modes.append(raw_mode)

    return final_rows, boundaries


def _track_summary(rows: list[dict]):
    tracked_x = [float(row["tracked_nozzle_x_px"]) for row in rows if row.get("tracked_nozzle_x_px") is not None]
    tracked_y = [float(row["tracked_nozzle_y_px"]) for row in rows if row.get("tracked_nozzle_y_px") is not None]
    confidence = [float(row["tracked_confidence"]) for row in rows if row.get("tracked_confidence") is not None]
    raw_mode_counts = {}
    final_mode_counts = {}
    for row in rows:
        raw_mode = _clean_text(row.get("raw_mode")) or "no_signal"
        final_mode = _clean_text(row.get("final_mode")) or "no_signal"
        raw_mode_counts[raw_mode] = int(raw_mode_counts.get(raw_mode, 0) + 1)
        final_mode_counts[final_mode] = int(final_mode_counts.get(final_mode, 0) + 1)
    return {
        "frame_count": len(rows),
        "tracked_x_min": min(tracked_x) if tracked_x else None,
        "tracked_x_max": max(tracked_x) if tracked_x else None,
        "tracked_y_min": min(tracked_y) if tracked_y else None,
        "tracked_y_max": max(tracked_y) if tracked_y else None,
        "tracked_confidence_min": min(confidence) if confidence else None,
        "tracked_confidence_max": max(confidence) if confidence else None,
        "tracked_confidence_mean": float(np.mean(confidence)) if confidence else None,
        "filled_frame_count": int(sum(1 for row in rows if bool(row.get("filled_from_segment")))),
        "segment_count": int(max([int(row["segment_id"]) for row in rows], default=0)),
        "raw_mode_counts": raw_mode_counts,
        "final_mode_counts": final_mode_counts,
    }


def _plot_track(rows: list[dict], boundaries: list[dict], path: Path):
    frame_index = [_int_or_none(row["capture_index"]) for row in rows]
    raw_x = [row.get("raw_nozzle_x_px") for row in rows]
    raw_y = [row.get("raw_nozzle_y_px") for row in rows]
    tracked_x = [row.get("tracked_nozzle_x_px") for row in rows]
    tracked_y = [row.get("tracked_nozzle_y_px") for row in rows]

    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(frame_index, tracked_x, color="#d81b60", linewidth=2, label="tracked x")
    axes[0].scatter(frame_index, raw_x, color="#8e24aa", s=18, alpha=0.65, label="raw x")
    axes[0].set_ylabel("Nozzle x (px)")
    axes[0].legend(loc="best")

    axes[1].plot(frame_index, tracked_y, color="#1e88e5", linewidth=2, label="tracked y")
    axes[1].scatter(frame_index, raw_y, color="#43a047", s=18, alpha=0.65, label="raw y")
    axes[1].set_ylabel("Nozzle y (px)")
    axes[1].set_xlabel("Capture index")
    axes[1].legend(loc="best")

    for boundary in boundaries:
        capture_index = int(boundary["boundary_index"])
        for axis in axes:
            axis.axvline(capture_index, color="#f4511e", linestyle="--", linewidth=1)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def _draw_label(image: np.ndarray, text: str):
    cv2.putText(
        image,
        text,
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def _resize_to_height(image: np.ndarray, target_height: int):
    height, width = image.shape[:2]
    scale = float(target_height) / float(max(1, height))
    target_width = max(1, int(round(width * scale)))
    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _marker(image: np.ndarray, point, color):
    if point is None or point[0] is None or point[1] is None:
        return image
    x, y = point
    cv2.drawMarker(
        image,
        (int(round(float(x))), int(round(float(y)))),
        color,
        markerType=cv2.MARKER_CROSS,
        markerSize=16,
        thickness=2,
    )
    return image


def _crop_with_padding(image: np.ndarray, *, center_x: int, center_y: int, half_width: int, top_pad: int, bottom_pad: int):
    x0 = int(center_x - half_width)
    x1 = int(center_x + half_width)
    y0 = int(center_y - top_pad)
    y1 = int(center_y + bottom_pad)

    src_x0 = max(0, x0)
    src_x1 = min(image.shape[1], x1)
    src_y0 = max(0, y0)
    src_y1 = min(image.shape[0], y1)
    crop = image[src_y0:src_y1, src_x0:src_x1]

    pad_left = max(0, -x0)
    pad_right = max(0, x1 - image.shape[1])
    pad_top = max(0, -y0)
    pad_bottom = max(0, y1 - image.shape[0])
    if pad_left or pad_right or pad_top or pad_bottom:
        crop = cv2.copyMakeBorder(
            crop,
            pad_top,
            pad_bottom,
            pad_left,
            pad_right,
            borderType=cv2.BORDER_REPLICATE,
        )
    return crop, src_x0, src_y0, pad_left, pad_top


def _build_sample_panel(gray: np.ndarray, diagnostics: dict, track_row: dict):
    search = diagnostics["search"]
    full = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(full, (search["x0"], search["y0"]), (search["x1"], search["y1"]), (0, 255, 255), 2)
    full = _marker(full, (track_row.get("raw_nozzle_x_px"), track_row.get("raw_nozzle_y_px")), (0, 255, 0))
    full = _marker(full, (track_row.get("tracked_nozzle_x_px"), track_row.get("tracked_nozzle_y_px")), (0, 0, 255))
    full = _draw_label(
        full,
        f"frame {track_row['capture_index']} raw={track_row['raw_mode']} final={track_row['final_mode']}",
    )

    search_gray = diagnostics["search_gray"]
    top_crop = search_gray[: min(search_gray.shape[0], 120), :]
    top_panel = cv2.cvtColor(top_crop, cv2.COLOR_GRAY2BGR)
    if track_row.get("static_line_y_px") is not None:
        local_y = int(round(float(track_row["static_line_y_px"]) - search["y0"]))
        cv2.line(top_panel, (0, local_y), (top_panel.shape[1] - 1, local_y), (255, 255, 0), 2)
        top_panel = _marker(
            top_panel,
            (
                float(track_row["static_line_x_px"]) - search["x0"],
                float(track_row["static_line_y_px"]) - search["y0"],
            ),
            (255, 255, 0),
        )
        cv2.circle(
            top_panel,
            (
                int(round(float(track_row["static_line_x_px"]) - search["x0"])),
                int(round(float(track_row["static_line_y_px"]) - search["y0"])),
            ),
            10,
            (255, 128, 0),
            2,
        )
    if track_row.get("only_nozzle_selected_roi_center_y_px") is not None:
        roi_center_local_y = int(round(float(track_row["only_nozzle_selected_roi_center_y_px"]) - search["y0"]))
        cv2.line(top_panel, (0, roi_center_local_y), (top_panel.shape[1] - 1, roi_center_local_y), (255, 0, 255), 1)
    top_panel = _draw_label(top_panel, "top ROI / only-nozzle cue")

    attached_panel = cv2.cvtColor(search_gray, cv2.COLOR_GRAY2BGR)
    contour_mask = diagnostics.get("contour_mask")
    strong_mask = diagnostics.get("strong_mask")
    candidate_mask = diagnostics["candidate_mask"]
    if contour_mask is not None:
        attached_panel[contour_mask > 0] = (28, 28, 180)
    if strong_mask is not None:
        attached_panel[strong_mask > 0] = (24, 88, 220)
    attached_panel[candidate_mask > 0] = (32, 32, 235)
    search_center_y_px = track_row.get("visible_line_search_center_y_px")
    search_radius_px = track_row.get("visible_line_search_radius_px")
    stable_visible_line_y_px = track_row.get("stable_visible_line_y_px")
    provisional_visible_line_y_px = track_row.get("provisional_visible_line_y_px")
    acquisition_upper_bound_y_px = track_row.get("visible_line_acquisition_upper_bound_y_px")
    line_band_y_px = track_row.get("line_band_y_px")
    bridge_x0_px = track_row.get("visible_line_bridge_x0_px")
    bridge_x1_px = track_row.get("visible_line_bridge_x1_px")
    late_widening_y_px = track_row.get("late_widening_y_px")
    geometry = diagnostics["geometry"]
    if geometry is not None:
        contour = geometry.get("contour")
        if contour is not None and len(contour) >= 3:
            cv2.polylines(attached_panel, [contour.astype(np.int32)], True, (255, 128, 0), 2)
        points = np.column_stack(
            [
                np.round(geometry["centerlines"]).astype(np.int32),
                geometry["rows"].astype(np.int32),
            ]
        )
        if len(points) >= 2:
            cv2.polylines(attached_panel, [points.reshape(-1, 1, 2)], False, (0, 255, 255), 2)
    if search_center_y_px is not None and search_radius_px is not None:
        local_center_y = int(round(float(search_center_y_px) - search["y0"]))
        half_range = int(round(float(search_radius_px)))
        cv2.line(attached_panel, (0, max(0, local_center_y - half_range)), (attached_panel.shape[1] - 1, max(0, local_center_y - half_range)), (255, 0, 255), 1)
        cv2.line(attached_panel, (0, min(attached_panel.shape[0] - 1, local_center_y + half_range)), (attached_panel.shape[1] - 1, min(attached_panel.shape[0] - 1, local_center_y + half_range)), (255, 0, 255), 1)
    if stable_visible_line_y_px is not None:
        local_y = int(round(float(stable_visible_line_y_px) - search["y0"]))
        cv2.line(attached_panel, (0, local_y), (attached_panel.shape[1] - 1, local_y), (255, 0, 255), 2)
    if acquisition_upper_bound_y_px is not None:
        local_y = int(round(float(acquisition_upper_bound_y_px) - search["y0"]))
        cv2.line(attached_panel, (0, local_y), (attached_panel.shape[1] - 1, local_y), (255, 128, 255), 1)
    for key, color, thickness in [
        ("visible_line_band_top_y_px", (0, 200, 255), 1),
        ("visible_line_band_bottom_y_px", (0, 200, 255), 1),
        ("late_plateau_band_top_y_px", (0, 128, 255), 1),
        ("late_plateau_band_bottom_y_px", (0, 128, 255), 1),
        ("pending_visible_line_y_px", (128, 0, 255), 1),
        ("provisional_visible_line_y_px", (128, 0, 255), 2),
    ]:
        value = track_row.get(key)
        if value is None:
            continue
        local_y = int(round(float(value) - search["y0"]))
        cv2.line(attached_panel, (0, local_y), (attached_panel.shape[1] - 1, local_y), color, thickness)
    for key, color in [
        ("neck_y_px", (255, 128, 0)),
        ("line_band_y_px", (0, 255, 255)),
        ("separation_band_y_px", (0, 128, 255)),
    ]:
        value = track_row.get(key)
        if value is None:
            continue
        local_y = int(round(float(value) - search["y0"]))
        cv2.line(attached_panel, (0, local_y), (attached_panel.shape[1] - 1, local_y), color, 2)
    if line_band_y_px is not None and bridge_x0_px is not None and bridge_x1_px is not None:
        bridge_local_y = int(round(float(line_band_y_px) - search["y0"]))
        bridge_local_x0 = int(round(float(bridge_x0_px) - search["x0"]))
        bridge_local_x1 = int(round(float(bridge_x1_px) - search["x0"]))
        cv2.line(attached_panel, (bridge_local_x0, bridge_local_y), (bridge_local_x1, bridge_local_y), (0, 255, 0), 3)
    if late_widening_y_px is not None:
        widening_local_y = int(round(float(late_widening_y_px) - search["y0"]))
        cv2.line(attached_panel, (0, widening_local_y), (attached_panel.shape[1] - 1, widening_local_y), (0, 128, 255), 2)
    if track_row.get("raw_nozzle_x_px") is not None and track_row.get("raw_nozzle_y_px") is not None:
        attached_panel = _marker(
            attached_panel,
            (
                float(track_row["raw_nozzle_x_px"]) - search["x0"],
                float(track_row["raw_nozzle_y_px"]) - search["y0"],
            ),
            (0, 255, 0),
        )
    if track_row.get("tracked_nozzle_x_px") is not None and track_row.get("tracked_nozzle_y_px") is not None:
        attached_panel = _marker(
            attached_panel,
            (
                float(track_row["tracked_nozzle_x_px"]) - search["x0"],
                float(track_row["tracked_nozzle_y_px"]) - search["y0"],
            ),
            (0, 0, 255),
        )
    contour_text = (
        f"contour={track_row.get('contour_completeness_score', 0.0):.2f} "
        f"bilat={track_row.get('contour_bilateral_row_fraction', 0.0):.2f} "
        f"widen={track_row.get('late_widening_score', 0.0):.2f} "
        f"used={bool(track_row.get('late_widening_used'))} "
        f"plateau_only={bool(track_row.get('visible_line_used_plateau_only_fallback'))} "
        f"late_band={bool(track_row.get('visible_line_valid_late_band'))} "
        f"clip={bool(track_row.get('contour_clipped_warning'))} "
        f"hollow={bool(track_row.get('hollow_bulb_guard_active'))}"
    )
    if bool(track_row.get("bridge_suppressed_by_clipped_contour")):
        contour_text += " bridge-suppressed"
    if bool(track_row.get("bridge_suppressed_by_plateau")):
        contour_text += " plateau-suppressed"
    if bool(track_row.get("bridge_suppressed_by_prior_conflict")):
        contour_text += " prior-suppressed"
    attached_panel = _draw_label(attached_panel, contour_text[:96])

    zoom_center_x = int(round((track_row.get("tracked_nozzle_x_px") or ((search["x0"] + search["x1"]) / 2.0)) - search["x0"]))
    zoom_center_y = int(round((track_row.get("tracked_nozzle_y_px") or ((search["y0"] + search["y1"]) / 2.0)) - search["y0"]))
    zoom_gray, crop_x0, crop_y0, pad_left, pad_top = _crop_with_padding(
        search_gray,
        center_x=zoom_center_x,
        center_y=zoom_center_y,
        half_width=80,
        top_pad=70,
        bottom_pad=100,
    )
    zoom = cv2.cvtColor(zoom_gray, cv2.COLOR_GRAY2BGR)

    for key, color in [
        ("neck_y_px", (255, 128, 0)),
        ("line_band_y_px", (0, 255, 255)),
        ("bright_core_upper_y_px", (255, 255, 0)),
        ("bright_core_lower_y_px", (0, 255, 255)),
        ("separation_band_y_px", (0, 128, 255)),
        ("late_widening_y_px", (0, 128, 255)),
    ]:
        value = track_row.get(key)
        if value is None:
            continue
        local_y = int(round(float(value) - search["y0"] - crop_y0 + pad_top))
        cv2.line(zoom, (0, local_y), (zoom.shape[1] - 1, local_y), color, 2)
    if search_center_y_px is not None and search_radius_px is not None:
        zoom_search_center_y = int(round(float(search_center_y_px) - search["y0"] - crop_y0 + pad_top))
        zoom_half_range = int(round(float(search_radius_px)))
        cv2.line(zoom, (0, max(0, zoom_search_center_y - zoom_half_range)), (zoom.shape[1] - 1, max(0, zoom_search_center_y - zoom_half_range)), (255, 0, 255), 1)
        cv2.line(zoom, (0, min(zoom.shape[0] - 1, zoom_search_center_y + zoom_half_range)), (zoom.shape[1] - 1, min(zoom.shape[0] - 1, zoom_search_center_y + zoom_half_range)), (255, 0, 255), 1)
    if stable_visible_line_y_px is not None:
        stable_local_y = int(round(float(stable_visible_line_y_px) - search["y0"] - crop_y0 + pad_top))
        cv2.line(zoom, (0, stable_local_y), (zoom.shape[1] - 1, stable_local_y), (255, 0, 255), 2)
    for key, color, thickness in [
        ("visible_line_band_top_y_px", (0, 200, 255), 1),
        ("visible_line_band_bottom_y_px", (0, 200, 255), 1),
        ("late_plateau_band_top_y_px", (0, 128, 255), 1),
        ("late_plateau_band_bottom_y_px", (0, 128, 255), 1),
        ("pending_visible_line_y_px", (128, 0, 255), 1),
        ("provisional_visible_line_y_px", (128, 0, 255), 2),
        ("visible_line_acquisition_upper_bound_y_px", (255, 128, 255), 1),
        ("only_nozzle_selected_roi_center_y_px", (255, 0, 255), 1),
    ]:
        value = track_row.get(key)
        if value is None:
            continue
        local_y = int(round(float(value) - search["y0"] - crop_y0 + pad_top))
        cv2.line(zoom, (0, local_y), (zoom.shape[1] - 1, local_y), color, thickness)
    if line_band_y_px is not None and bridge_x0_px is not None and bridge_x1_px is not None:
        bridge_local_y = int(round(float(line_band_y_px) - search["y0"] - crop_y0 + pad_top))
        bridge_local_x0 = int(round(float(bridge_x0_px) - search["x0"] - crop_x0 + pad_left))
        bridge_local_x1 = int(round(float(bridge_x1_px) - search["x0"] - crop_x0 + pad_left))
        cv2.line(zoom, (bridge_local_x0, bridge_local_y), (bridge_local_x1, bridge_local_y), (0, 255, 0), 3)

    if track_row.get("raw_nozzle_x_px") is not None and track_row.get("raw_nozzle_y_px") is not None:
        zoom = _marker(
            zoom,
            (
                float(track_row["raw_nozzle_x_px"]) - search["x0"] - crop_x0 + pad_left,
                float(track_row["raw_nozzle_y_px"]) - search["y0"] - crop_y0 + pad_top,
            ),
            (0, 255, 0),
        )
    if track_row.get("tracked_nozzle_x_px") is not None and track_row.get("tracked_nozzle_y_px") is not None:
        zoom = _marker(
            zoom,
            (
                float(track_row["tracked_nozzle_x_px"]) - search["x0"] - crop_x0 + pad_left,
                float(track_row["tracked_nozzle_y_px"]) - search["y0"] - crop_y0 + pad_top,
            ),
            (0, 0, 255),
        )
    zoom = _draw_label(
        zoom,
        (
            f"fill={track_row['used_segment_fill']} "
            f"drop={track_row.get('compact_droplet_score', 0.0):.2f} "
            f"neck={track_row.get('neck_score', 0.0):.2f} "
            f"line={track_row.get('line_band_score', 0.0):.2f} "
            f"only={track_row.get('only_nozzle_score', 0.0):.2f} "
            f"contour={track_row.get('contour_completeness_score', 0.0):.2f} "
            f"widen={track_row.get('late_widening_score', 0.0):.2f} "
            f"used={bool(track_row.get('late_widening_used'))} "
            f"lower_fix={bool(track_row.get('visible_line_lower_peak_prior_constrained'))} "
            f"hyst={bool(track_row.get('visible_line_used_hysteresis'))} "
            f"relaxed={bool(track_row.get('visible_line_used_relaxed_fallback'))} "
            f"plateau_only={bool(track_row.get('visible_line_used_plateau_only_fallback'))} "
            f"late_band={bool(track_row.get('visible_line_valid_late_band'))} "
            f"plateau_mode={track_row.get('visible_line_plateau_mode') or 'n/a'} "
            f"plateau_acq={bool(track_row.get('plateau_suppressed_on_acquisition'))} "
            f"hollow={bool(track_row.get('hollow_bulb_guard_active'))} "
            f"hollow_reject={bool(track_row.get('visible_line_rejected_by_hollow_bulb_guard'))} "
            f"upper_reject={bool(track_row.get('visible_line_rejected_by_upper_cue_conflict'))} "
            f"clip={bool(track_row.get('contour_clipped_warning'))} "
            f"plateau_suppr={bool(track_row.get('bridge_suppressed_by_plateau'))} "
            f"prior_suppr={bool(track_row.get('bridge_suppressed_by_prior_conflict'))} "
            f"drop_suppr={bool(track_row.get('droplet_suppressed_as_reflection'))} "
            f"only_tr={bool(track_row.get('only_nozzle_transition_scoring_used'))} "
            f"only_d={('n/a' if track_row.get('only_nozzle_distance_from_stable_prior_px') is None else format(float(track_row.get('only_nozzle_distance_from_stable_prior_px')), '.1f'))} "
            f"only_src={track_row.get('only_nozzle_candidate_source') or 'n/a'} "
            f"band={bool(track_row.get('only_nozzle_prior_band_used'))} "
            f"band_n={int(track_row.get('only_nozzle_prior_band_candidate_count') or 0)} "
            f"far_reject={bool(track_row.get('only_nozzle_rejected_far_from_prior'))} "
            f"low_reject={bool(track_row.get('only_nozzle_rejected_lower_reflection'))} "
            f"anchor_low={bool(track_row.get('only_nozzle_anchor_rejected_as_low_reflection'))} "
            f"fill_src={track_row.get('transition_fill_source') or 'none'}"
        ),
    )

    target_height = 320
    return cv2.hconcat(
        [
            _resize_to_height(full, target_height),
            _resize_to_height(top_panel, target_height),
            _resize_to_height(attached_panel, target_height),
            _resize_to_height(zoom, target_height),
        ]
    )


def _raw_track_row(run_id: str, frame_row: dict, diagnostics: dict):
    search = diagnostics["search"]
    geometry = diagnostics["geometry"]

    candidate_top = None if geometry is None else int(search["y0"] + geometry["bbox_y0"])
    candidate_bottom = None if geometry is None else int(search["y0"] + geometry["bbox_y1"])
    candidate_width = None if geometry is None else int(geometry["max_width"])

    return {
        "run_id": run_id,
        "capture_id": frame_row.get("capture_id"),
        "capture_index": _int_or_none(frame_row.get("capture_index")),
        "image_relpath": frame_row.get("image_relpath"),
        "image_exists": bool(frame_row.get("image_exists")),
        "captured_at_utc": frame_row.get("captured_at_utc"),
        "flash_delay_us": _int_or_none(frame_row.get("flash_delay_us")),
        "delay_from_emergence_us": _int_or_none(frame_row.get("delay_from_emergence_us")),
        "search_x0": int(search["x0"]),
        "search_y0": int(search["y0"]),
        "search_x1": int(search["x1"]),
        "search_y1": int(search["y1"]),
        "search_width": int(search["width"]),
        "search_height": int(search["height"]),
        "raw_nozzle_x_px": diagnostics.get("raw_x"),
        "raw_nozzle_y_px": diagnostics.get("raw_y"),
        "tracked_nozzle_x_px": None,
        "tracked_nozzle_y_px": None,
        "raw_confidence": float(diagnostics.get("confidence") or 0.0),
        "tracked_confidence": None,
        "detection_mode": str(diagnostics.get("mode") or "no_signal"),
        "raw_mode": str(diagnostics.get("mode") or "no_signal"),
        "final_mode": str(diagnostics.get("mode") or "no_signal"),
        "filled_from_segment": False,
        "used_segment_fill": False,
        "segment_id": None,
        "shift_event_before": False,
        "static_line_x_px": None
        if diagnostics.get("static_line_x_local") is None
        else float(search["x0"] + diagnostics["static_line_x_local"]),
        "static_line_y_px": None
        if diagnostics.get("static_line_y_local") is None
        else float(search["y0"] + diagnostics["static_line_y_local"]),
        "attached_component_centroid_x_px": None
        if diagnostics.get("attached_component_centroid_x_local") is None
        else float(search["x0"] + diagnostics["attached_component_centroid_x_local"]),
        "attached_component_centroid_y_px": None
        if diagnostics.get("attached_component_centroid_y_local") is None
        else float(search["y0"] + diagnostics["attached_component_centroid_y_local"]),
        "attached_component_area_px": 0 if geometry is None else int(geometry["area"]),
        "bright_core_upper_y_px": None
        if diagnostics.get("bright_core_upper_y_local") is None
        else float(search["y0"] + diagnostics["bright_core_upper_y_local"]),
        "bright_core_lower_y_px": None
        if diagnostics.get("bright_core_lower_y_local") is None
        else float(search["y0"] + diagnostics["bright_core_lower_y_local"]),
        "separation_band_y_px": None
        if diagnostics.get("separation_band_y_local") is None
        else float(search["y0"] + diagnostics["separation_band_y_local"]),
        "compact_droplet_score": float(diagnostics.get("compact_droplet_score") or 0.0),
        "neck_y_px": None
        if diagnostics.get("neck_y_local") is None
        else float(search["y0"] + diagnostics["neck_y_local"]),
        "neck_width_px": None if diagnostics.get("neck_width_px") is None else float(diagnostics["neck_width_px"]),
        "neck_score": float(diagnostics.get("neck_score") or 0.0),
        "contour_completeness_score": float(diagnostics.get("contour_completeness_score") or 0.0),
        "contour_bilateral_row_fraction": float(diagnostics.get("contour_bilateral_row_fraction") or 0.0),
        "contour_width_median_px": None
        if diagnostics.get("contour_width_median_px") is None
        else float(diagnostics["contour_width_median_px"]),
        "contour_width_iqr_px": None
        if diagnostics.get("contour_width_iqr_px") is None
        else float(diagnostics["contour_width_iqr_px"]),
        "contour_clipped_warning": bool(diagnostics.get("contour_clipped_warning")),
        "stable_visible_line_y_px": None
        if diagnostics.get("stable_visible_line_y_local") is None
        else float(search["y0"] + diagnostics["stable_visible_line_y_local"]),
        "pending_visible_line_y_px": None,
        "provisional_visible_line_y_px": None,
        "provisional_visible_line_count": 0,
        "visible_line_search_center_y_px": None
        if diagnostics.get("visible_line_search_center_y_local") is None
        else float(search["y0"] + diagnostics["visible_line_search_center_y_local"]),
        "visible_line_search_radius_px": None
        if diagnostics.get("visible_line_search_radius_px") is None
        else int(diagnostics["visible_line_search_radius_px"]),
        "visible_line_acquisition_search_center_y_px": None
        if diagnostics.get("visible_line_acquisition_search_center_y_local") is None
        else float(search["y0"] + diagnostics["visible_line_acquisition_search_center_y_local"]),
        "visible_line_acquisition_upper_bound_y_px": None
        if diagnostics.get("visible_line_acquisition_upper_bound_y_local") is None
        else float(search["y0"] + diagnostics["visible_line_acquisition_upper_bound_y_local"]),
        "line_band_y_px": None
        if diagnostics.get("line_band_y_local") is None
        else float(search["y0"] + diagnostics["line_band_y_local"]),
        "line_band_score": float(diagnostics.get("line_band_score") or 0.0),
        "late_widening_y_px": None
        if diagnostics.get("late_widening_y_local") is None
        else float(search["y0"] + diagnostics["late_widening_y_local"]),
        "late_widening_score": float(diagnostics.get("late_widening_score") or 0.0),
        "late_widening_used": bool(diagnostics.get("late_widening_used")),
        "visible_line_band_top_y_px": None
        if diagnostics.get("visible_line_band_top_y_local") is None
        else float(search["y0"] + diagnostics["visible_line_band_top_y_local"]),
        "visible_line_band_bottom_y_px": None
        if diagnostics.get("visible_line_band_bottom_y_local") is None
        else float(search["y0"] + diagnostics["visible_line_band_bottom_y_local"]),
        "visible_line_band_height_px": None
        if diagnostics.get("visible_line_band_height_px") is None
        else int(diagnostics["visible_line_band_height_px"]),
        "visible_line_span_width_px": None
        if diagnostics.get("visible_line_span_width_px") is None
        else int(diagnostics["visible_line_span_width_px"]),
        "visible_line_span_fraction": None
        if diagnostics.get("visible_line_span_fraction") is None
        else float(diagnostics["visible_line_span_fraction"]),
        "visible_line_dark_delta": None
        if diagnostics.get("visible_line_dark_delta") is None
        else float(diagnostics["visible_line_dark_delta"]),
        "visible_line_vertical_overlap": None
        if diagnostics.get("visible_line_vertical_overlap") is None
        else float(diagnostics["visible_line_vertical_overlap"]),
        "visible_line_used_hysteresis": bool(diagnostics.get("visible_line_used_hysteresis")),
        "visible_line_used_relaxed_fallback": bool(diagnostics.get("visible_line_used_relaxed_fallback")),
        "visible_line_used_plateau_only_fallback": bool(diagnostics.get("visible_line_used_plateau_only_fallback")),
        "visible_line_valid_late_band": bool(diagnostics.get("visible_line_valid_late_band")),
        "visible_line_plateau_mode": diagnostics.get("visible_line_plateau_mode"),
        "plateau_suppressed_on_acquisition": bool(diagnostics.get("plateau_suppressed_on_acquisition")),
        "hollow_bulb_guard_active": bool(diagnostics.get("hollow_bulb_guard_active")),
        "visible_line_rejected_by_hollow_bulb_guard": bool(diagnostics.get("visible_line_rejected_by_hollow_bulb_guard")),
        "visible_line_rejected_by_upper_cue_conflict": bool(diagnostics.get("visible_line_rejected_by_upper_cue_conflict")),
        "visible_line_lower_peak_prior_constrained": bool(diagnostics.get("visible_line_lower_peak_prior_constrained")),
        "visible_line_effective_lower_peak_y_px": None
        if diagnostics.get("visible_line_effective_lower_peak_y_local") is None
        else float(search["y0"] + diagnostics["visible_line_effective_lower_peak_y_local"]),
        "bridge_suppressed_by_clipped_contour": bool(diagnostics.get("bridge_suppressed_by_clipped_contour")),
        "bridge_suppressed_by_plateau": bool(diagnostics.get("bridge_suppressed_by_plateau")),
        "bridge_suppressed_by_prior_conflict": bool(diagnostics.get("bridge_suppressed_by_prior_conflict")),
        "late_bridge_delta_from_prior_px": None
        if diagnostics.get("late_bridge_delta_from_prior_px") is None
        else float(diagnostics["late_bridge_delta_from_prior_px"]),
        "late_plateau_delta_from_prior_px": None
        if diagnostics.get("late_plateau_delta_from_prior_px") is None
        else float(diagnostics["late_plateau_delta_from_prior_px"]),
        "visible_line_bridge_x0_px": None
        if diagnostics.get("visible_line_bridge_x0_local") is None
        else float(search["x0"] + diagnostics["visible_line_bridge_x0_local"]),
        "visible_line_bridge_x1_px": None
        if diagnostics.get("visible_line_bridge_x1_local") is None
        else float(search["x0"] + diagnostics["visible_line_bridge_x1_local"]),
        "late_plateau_band_top_y_px": None
        if diagnostics.get("late_plateau_band_top_y_local") is None
        else float(search["y0"] + diagnostics["late_plateau_band_top_y_local"]),
        "late_plateau_band_bottom_y_px": None
        if diagnostics.get("late_plateau_band_bottom_y_local") is None
        else float(search["y0"] + diagnostics["late_plateau_band_bottom_y_local"]),
        "late_plateau_picked_y_px": None
        if diagnostics.get("late_plateau_picked_y_local") is None
        else float(search["y0"] + diagnostics["late_plateau_picked_y_local"]),
        "only_nozzle_y_px": None
        if diagnostics.get("only_nozzle_y_local") is None
        else float(search["y0"] + diagnostics["only_nozzle_y_local"]),
        "only_nozzle_score": float(diagnostics.get("only_nozzle_score") or 0.0),
        "only_nozzle_roi_centers_y_px": _serialize_float_list(
            None
            if diagnostics.get("only_nozzle_roi_centers_y_local") is None
            else [float(search["y0"] + float(value)) for value in diagnostics["only_nozzle_roi_centers_y_local"]]
        ),
        "only_nozzle_selected_roi_center_y_px": None
        if diagnostics.get("only_nozzle_selected_roi_center_y_local") is None
        else float(search["y0"] + diagnostics["only_nozzle_selected_roi_center_y_local"]),
        "only_nozzle_candidate_source": diagnostics.get("only_nozzle_candidate_source"),
        "only_nozzle_prior_band_used": bool(diagnostics.get("only_nozzle_prior_band_used")),
        "only_nozzle_prior_band_candidate_count": int(diagnostics.get("only_nozzle_prior_band_candidate_count") or 0),
        "only_nozzle_rejected_far_from_prior": bool(diagnostics.get("only_nozzle_rejected_far_from_prior")),
        "only_nozzle_transition_scoring_used": bool(diagnostics.get("only_nozzle_transition_scoring_used")),
        "only_nozzle_distance_from_stable_prior_px": None
        if diagnostics.get("only_nozzle_distance_from_stable_prior_px") is None
        else float(diagnostics["only_nozzle_distance_from_stable_prior_px"]),
        "only_nozzle_rejected_lower_reflection": bool(diagnostics.get("only_nozzle_rejected_lower_reflection")),
        "only_nozzle_anchor_rejected_as_low_reflection": bool(diagnostics.get("only_nozzle_anchor_rejected_as_low_reflection")),
        "droplet_suppressed_as_reflection": bool(diagnostics.get("droplet_suppressed_as_reflection")),
        "attached_support_score": float(diagnostics.get("attached_support_score") or 0.0),
        "profile_valley_score": float(diagnostics.get("valley_score") or 0.0),
        "candidate_component_count": int(len(diagnostics.get("components") or [])),
        "top_candidate_count": int(len(diagnostics.get("top_candidates") or [])),
        "candidate_mask_area_px": int(diagnostics.get("candidate_mask_area_px") or 0),
        "candidate_band_width_px": candidate_width,
        "candidate_top_y_px": candidate_top,
        "candidate_bottom_y_px": candidate_bottom,
        "transition_fill_used": False,
        "transition_fill_source": None,
        "anchor_rejected_as_reflection": False,
        "sample_frame": False,
    }


def export_stage2_nozzle(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    sample_count: int = 6,
    extra_frame_indices: list[int] | None = None,
    search_width_frac: float = 0.22,
    search_top_frac: float = 0.08,
    search_bottom_frac: float = 0.30,
    blur_sigma: float = 12.0,
    residual_scale: float = 2.5,
    residual_threshold: int = 18,
    min_area_px: int = 120,
    top_band_slack_px: int = 14,
    shift_threshold_px: float = 6.0,
    confidence_threshold: float = 0.55,
):
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )

    output_path = Path(output_root).expanduser().resolve() if output_root else default_output_root(experiment_root)
    output_path.mkdir(parents=True, exist_ok=True)

    run_manifests = []
    for run_row in inventory["selected_runs"]:
        run_id = str(run_row["run_id"])
        frame_rows = list(inventory["frames_by_run_id"][run_id])
        if not frame_rows:
            raise ValueError(f"No frame index rows available for run: {run_id}")

        raw_rows, frame_diagnostics = _detect_run_raw_rows(
            run_id,
            frame_rows,
            search_width_frac=search_width_frac,
            search_top_frac=search_top_frac,
            search_bottom_frac=search_bottom_frac,
            blur_sigma=blur_sigma,
            residual_scale=residual_scale,
            residual_threshold=residual_threshold,
            min_area_px=min_area_px,
            top_band_slack_px=top_band_slack_px,
        )

        tracked_rows, shift_events = _apply_tracking(
            raw_rows,
            shift_threshold_px=shift_threshold_px,
            confidence_threshold=confidence_threshold,
        )
        sample_indices = set(
            _sample_indices(
                len(frame_rows),
                sample_count=sample_count,
                extra_frame_indices=extra_frame_indices,
            )
        )
        sample_indices.update(int(event["previous_capture_index"]) for event in shift_events if event.get("previous_capture_index"))
        sample_indices.update(int(event["next_capture_index"]) for event in shift_events if event.get("next_capture_index"))

        stage_dir = output_path / "runs" / run_id / NOZZLE_STAGE_DIRNAME
        stage_dir.mkdir(parents=True, exist_ok=True)
        sample_dir = stage_dir / "samples"
        if sample_dir.exists():
            for stale_panel in sample_dir.glob("*.png"):
                stale_panel.unlink()

        sample_panels = []
        sample_panel_paths = []
        for frame_row, tracked_row, diagnostics in zip(frame_rows, tracked_rows, frame_diagnostics):
            capture_index = _int_or_none(tracked_row["capture_index"]) or 0
            if capture_index not in sample_indices:
                continue
            tracked_row["sample_frame"] = True
            image_path = Path(str(frame_row["image_abs_path"]))
            gray = _load_gray_image(image_path)
            panel = _build_sample_panel(gray, diagnostics, tracked_row)
            panel_path = sample_dir / f"frame_{capture_index:03d}_panel.png"
            panel_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(panel_path), panel)
            sample_panels.append(panel)
            sample_panel_paths.append(str(panel_path))

        track_csv = stage_dir / "nozzle_track.csv"
        track_json = stage_dir / "nozzle_track.json"
        shift_json = stage_dir / "shift_events.json"
        summary_json = stage_dir / "nozzle_manifest.json"
        contact_sheet_png = stage_dir / "sample_contact_sheet.png"
        track_plot_png = stage_dir / "nozzle_track.png"

        _write_csv(track_csv, _preferred_columns(tracked_rows, TRACK_COLUMNS), tracked_rows)
        _write_json(track_json, {"rows": tracked_rows})
        _write_json(shift_json, {"shift_events": shift_events})
        if sample_panels:
            contact_sheet = cv2.vconcat(sample_panels)
            cv2.imwrite(str(contact_sheet_png), contact_sheet)
        _plot_track(tracked_rows, shift_events, track_plot_png)

        summary = {
            "schema_version": 2,
            "stage": "nozzle",
            "run_id": run_id,
            "run_dir": run_row["run_dir"],
            "search": {
                "width_frac": float(search_width_frac),
                "top_frac": float(search_top_frac),
                "bottom_frac": float(search_bottom_frac),
                "blur_sigma": float(blur_sigma),
                "residual_scale": float(residual_scale),
                "residual_threshold": int(residual_threshold),
                "min_area_px": int(min_area_px),
                "top_band_slack_px": int(top_band_slack_px),
            },
            "confidence_threshold": float(confidence_threshold),
            "shift_threshold_px": float(shift_threshold_px),
            "sample_capture_indices": sorted(sample_indices),
            "sample_panel_paths": sample_panel_paths,
            "outputs": {
                "nozzle_track_csv": str(track_csv),
                "nozzle_track_json": str(track_json),
                "shift_events_json": str(shift_json),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
                "nozzle_track_png": str(track_plot_png),
            },
            "summary": _track_summary(tracked_rows),
            "shift_events": shift_events,
        }
        _write_json(summary_json, summary)
        run_manifests.append(
            {
                "run_id": run_id,
                "run_dir": run_row["run_dir"],
                "nozzle_track_csv": str(track_csv),
                "nozzle_track_json": str(track_json),
                "shift_events_json": str(shift_json),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
                "nozzle_track_png": str(track_plot_png),
                "frame_count": len(tracked_rows),
                "sample_frame_count": len(sample_indices),
                "shift_event_count": len(shift_events),
            }
        )

    manifest = {
        "schema_version": 2,
        "stage": "nozzle",
        "experiment_root": inventory["experiment_root"],
        "output_root": str(output_path),
        "selected_run_count": len(run_manifests),
        "run_ids": [row["run_id"] for row in run_manifests],
        "search_width_frac": float(search_width_frac),
        "search_top_frac": float(search_top_frac),
        "search_bottom_frac": float(search_bottom_frac),
        "blur_sigma": float(blur_sigma),
        "residual_scale": float(residual_scale),
        "residual_threshold": int(residual_threshold),
        "min_area_px": int(min_area_px),
        "shift_threshold_px": float(shift_threshold_px),
        "confidence_threshold": float(confidence_threshold),
        "sample_count": int(sample_count),
        "extra_frame_indices": list(extra_frame_indices or []),
        "runs": run_manifests,
    }
    manifest_path = output_path / "nozzle_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest
