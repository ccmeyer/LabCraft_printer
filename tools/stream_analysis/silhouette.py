from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage

from tools.stream_analysis.dataset import (
    _clean_text,
    _int_or_none,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
)
from tools.stream_analysis.nozzle import _build_stage2_run


SILHOUETTE_STAGE_DIRNAME = "stage_03_silhouette"
INPUT_POLICY = "direct_threshold"

SILHOUETTE_METRIC_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "image_relpath",
    "image_exists",
    "captured_at_utc",
    "flash_delay_us",
    "delay_from_emergence_us",
    "tracked_nozzle_x_px",
    "tracked_nozzle_y_px",
    "tracked_confidence",
    "raw_mode",
    "final_mode",
    "segment_id",
    "shift_event_before",
    "input_policy",
    "threshold_method",
    "threshold_value",
    "roi_x0",
    "roi_y0",
    "roi_x1",
    "roi_y1",
    "roi_width",
    "roi_height",
    "corridor_x0",
    "corridor_x1",
    "corridor_width",
    "nozzle_guard_px",
    "cutoff_y_px",
    "raw_dark_pixel_count",
    "raw_dark_fraction",
    "filled_pixel_count",
    "filled_fraction",
    "fill_strategy",
    "fill_trigger_source",
    "open_bottom_interior_detected",
    "row_fill_added_pixel_count",
    "accepted_component_count",
    "accepted_detached_component_count",
    "attached_component_area_px",
    "detached_component_area_px_total",
    "accepted_total_area_px",
    "connected_component_count",
    "candidate_component_count",
    "selected_component_area_px",
    "selected_component_score",
    "selected_component_bbox_x_px",
    "selected_component_bbox_y_px",
    "selected_component_bbox_w_px",
    "selected_component_bbox_h_px",
    "selected_component_top_y_px",
    "selected_component_bottom_y_px",
    "selected_anchor_row_y_px",
    "selected_anchor_center_x_px",
    "silhouette_status",
    "failure_reason",
    "valid_row_count",
    "first_valid_y_px",
    "last_valid_y_px",
    "max_width_px",
    "sample_frame",
]

COMPONENT_METRIC_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "flash_delay_us",
    "component_id",
    "component_role",
    "component_rank",
    "component_area_px",
    "component_score",
    "bbox_x_px",
    "bbox_y_px",
    "bbox_w_px",
    "bbox_h_px",
    "top_y_px",
    "bottom_y_px",
    "anchor_row_y_px",
    "anchor_center_x_px",
    "fill_strategy",
    "fill_trigger_source",
    "open_bottom_interior_detected",
    "row_fill_added_pixel_count",
    "valid_row_count",
    "first_valid_y_px",
    "last_valid_y_px",
    "max_width_px",
]

EDGE_TRACE_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "flash_delay_us",
    "component_id",
    "component_role",
    "component_rank",
    "y_px",
    "x_left_px",
    "x_right_px",
    "width_px",
    "center_x_px",
]


def _load_gray_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not load grayscale image: {path}")
    return image


def _coerce_gray_image(image) -> np.ndarray:
    if image is None:
        raise ValueError("Image is required for silhouette analysis.")
    arr = np.asarray(image)
    if arr.ndim == 2:
        return arr.copy()
    if arr.ndim == 3:
        if arr.shape[2] == 1:
            return arr[:, :, 0].copy()
        return cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    raise ValueError("Unsupported image shape for silhouette analysis.")


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


def _dynamic_roi_bounds(
    image_shape,
    *,
    tracked_x_px: float | None,
    roi_width_frac: float,
    roi_top_frac: float,
    roi_bottom_frac: float,
):
    height, width = image_shape[:2]
    roi_width = max(1, int(round(width * float(roi_width_frac))))
    half_width = max(1, int(round(roi_width / 2.0)))
    center_x = width // 2 if tracked_x_px is None else int(round(float(tracked_x_px)))
    x0 = max(0, center_x - half_width)
    x1 = min(width, x0 + roi_width)
    x0 = max(0, x1 - roi_width)
    y0 = max(0, min(height - 1, int(round(height * float(roi_top_frac)))))
    y1 = max(y0 + 1, min(height, int(round(height * float(roi_bottom_frac)))))
    return {
        "x0": int(x0),
        "y0": int(y0),
        "x1": int(x1),
        "y1": int(y1),
        "width": int(x1 - x0),
        "height": int(y1 - y0),
    }


def _corridor_bounds(
    roi: dict,
    *,
    tracked_x_px: float | None,
    corridor_width_frac: float,
):
    corridor_width = max(1, int(round(int(roi["width"]) * float(corridor_width_frac))))
    half_width = max(1, int(round(corridor_width / 2.0)))
    if tracked_x_px is None:
        center_x = int(roi["x0"] + (roi["width"] / 2.0))
    else:
        center_x = int(round(float(tracked_x_px)))
    x0 = max(int(roi["x0"]), center_x - half_width)
    x1 = min(int(roi["x1"]), x0 + corridor_width)
    x0 = max(int(roi["x0"]), x1 - corridor_width)
    return {
        "x0": int(x0),
        "x1": int(x1),
        "width": int(x1 - x0),
    }


def _threshold_roi(roi_gray: np.ndarray):
    threshold_value, mask = cv2.threshold(
        roi_gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    return float(threshold_value), mask


def _apply_corridor_mask(mask: np.ndarray, roi: dict, corridor: dict):
    trimmed = np.zeros_like(mask)
    local_x0 = max(0, int(corridor["x0"]) - int(roi["x0"]))
    local_x1 = max(local_x0 + 1, int(corridor["x1"]) - int(roi["x0"]))
    trimmed[:, local_x0:local_x1] = mask[:, local_x0:local_x1]
    return trimmed


def _apply_nozzle_cutoff(mask: np.ndarray, roi: dict, *, cutoff_y_px: int | None):
    trimmed = mask.copy()
    if cutoff_y_px is None:
        trimmed[:, :] = 0
        return trimmed
    local_cutoff = max(0, min(trimmed.shape[0], int(cutoff_y_px) - int(roi["y0"])))
    trimmed[:local_cutoff, :] = 0
    return trimmed


def _clean_filled_mask(mask: np.ndarray):
    if mask.size <= 0:
        return np.zeros_like(mask)
    cleaned = mask.copy()
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, open_kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)
    filled = ndimage.binary_fill_holes(cleaned > 0)
    return (filled.astype(np.uint8) * 255)


def _row_envelope_fill(mask: np.ndarray):
    filled = np.zeros_like(mask)
    for row_local in np.flatnonzero(np.any(mask > 0, axis=1)):
        xs = np.flatnonzero(mask[row_local] > 0)
        if xs.size <= 0:
            continue
        filled[row_local, int(xs[0]) : int(xs[-1]) + 1] = 255
    return filled


def _find_open_bottom_interior_seed(
    selected_mask: np.ndarray,
    roi: dict,
    *,
    tracked_x_px: float | None,
    cutoff_y_px: int | None,
):
    if tracked_x_px is None or cutoff_y_px is None or selected_mask.size <= 0:
        return None

    local_x = int(round(float(tracked_x_px) - float(roi["x0"])))
    local_x = max(0, min(selected_mask.shape[1] - 1, local_x))
    start_y = max(0, min(selected_mask.shape[0] - 1, int(cutoff_y_px) - int(roi["y0"]) + 8))

    for row_local in range(start_y, selected_mask.shape[0]):
        xs = np.flatnonzero(selected_mask[row_local] > 0)
        if xs.size < 2:
            continue
        left_candidates = xs[xs < local_x]
        right_candidates = xs[xs > local_x]
        if left_candidates.size <= 0 or right_candidates.size <= 0:
            continue
        gap_x0 = int(left_candidates[-1]) + 1
        gap_x1 = int(right_candidates[0]) - 1
        if gap_x1 < gap_x0:
            continue
        if np.any(selected_mask[row_local, gap_x0 : gap_x1 + 1] > 0):
            continue
        return {
            "row_local": int(row_local),
            "seed_x_local": int((gap_x0 + gap_x1) // 2),
            "gap_x0_local": int(gap_x0),
            "gap_x1_local": int(gap_x1),
        }
    return None


def _background_component_border_info(background_mask: np.ndarray, *, seed_y_local: int, seed_x_local: int):
    if background_mask.size <= 0:
        return None
    if not bool(background_mask[seed_y_local, seed_x_local]):
        return None
    labels, _count = ndimage.label(background_mask)
    label = int(labels[seed_y_local, seed_x_local])
    if label <= 0:
        return None
    component = labels == label
    return {
        "touches_top": bool(np.any(component[0, :])),
        "touches_bottom": bool(np.any(component[-1, :])),
        "touches_left": bool(np.any(component[:, 0])),
        "touches_right": bool(np.any(component[:, -1])),
        "size_px": int(np.count_nonzero(component)),
    }


def _component_row_bounds(mask: np.ndarray, *, row_local: int, x0_local: int, x1_local: int):
    if row_local < 0 or row_local >= mask.shape[0]:
        return None
    xs = np.flatnonzero(mask[row_local] > 0)
    if xs.size <= 0:
        return None
    left_exists = bool(np.any(xs < int(x0_local)))
    right_exists = bool(np.any(xs > int(x1_local)))
    return {
        "left_exists": left_exists,
        "right_exists": right_exists,
    }


def _find_open_bottom_interior_component(
    selected_mask: np.ndarray,
    roi: dict,
    *,
    tracked_x_px: float | None,
    cutoff_y_px: int | None,
):
    if selected_mask.size <= 0 or cutoff_y_px is None:
        return None

    background_mask = selected_mask == 0
    labels, count = ndimage.label(background_mask)
    if count <= 0:
        return None

    tracked_x_local = None
    if tracked_x_px is not None:
        tracked_x_local = max(0, min(selected_mask.shape[1] - 1, int(round(float(tracked_x_px) - float(roi["x0"])))))
    cutoff_local = max(0, min(selected_mask.shape[0] - 1, int(cutoff_y_px) - int(roi["y0"])))
    min_top_local = max(0, min(selected_mask.shape[0] - 1, cutoff_local + 8))

    candidates = []
    for label in range(1, int(count) + 1):
        component = labels == int(label)
        size_px = int(np.count_nonzero(component))
        if size_px < 48:
            continue
        ys, xs = np.nonzero(component)
        if ys.size <= 0 or xs.size <= 0:
            continue
        y0_local = int(ys.min())
        y1_local = int(ys.max())
        x0_local = int(xs.min())
        x1_local = int(xs.max())
        height_rows = int(y1_local - y0_local + 1)
        touches_top = bool(np.any(component[0, :]))
        touches_bottom = bool(np.any(component[-1, :]))
        touches_left = bool(np.any(component[:, 0]))
        touches_right = bool(np.any(component[:, -1]))
        if not touches_bottom or touches_top or touches_left or touches_right:
            continue
        if y0_local < min_top_local or height_rows < 12:
            continue

        occupied_rows = []
        bounded_rows = 0
        centers = []
        for row_local in np.flatnonzero(np.any(component, axis=1)):
            row_xs = np.flatnonzero(component[row_local])
            if row_xs.size <= 0:
                continue
            row_x0 = int(row_xs[0])
            row_x1 = int(row_xs[-1])
            occupied_rows.append(int(row_local))
            centers.append((float(row_x0) + float(row_x1)) / 2.0)
            row_bounds = _component_row_bounds(
                selected_mask,
                row_local=int(row_local),
                x0_local=row_x0,
                x1_local=row_x1,
            )
            if row_bounds and row_bounds["left_exists"] and row_bounds["right_exists"]:
                bounded_rows += 1

        occupied_row_count = len(occupied_rows)
        if occupied_row_count <= 0:
            continue
        bounded_fraction = float(bounded_rows) / float(occupied_row_count)
        if bounded_fraction < 0.60:
            continue

        median_center_x_local = None if not centers else float(np.median(np.asarray(centers, dtype=float)))
        center_distance_px = (
            0.0
            if tracked_x_local is None or median_center_x_local is None
            else abs(float(median_center_x_local) - float(tracked_x_local))
        )
        candidates.append(
            {
                "label": int(label),
                "mask": component,
                "size_px": size_px,
                "height_rows": height_rows,
                "y0_local": y0_local,
                "y1_local": y1_local,
                "x0_local": x0_local,
                "x1_local": x1_local,
                "bounded_row_count": int(bounded_rows),
                "occupied_row_count": int(occupied_row_count),
                "bounded_fraction": float(bounded_fraction),
                "median_center_x_local": median_center_x_local,
                "tracked_x_distance_px": float(center_distance_px),
                "touches_top": touches_top,
                "touches_bottom": touches_bottom,
                "touches_left": touches_left,
                "touches_right": touches_right,
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda row: (
            -int(row["bounded_row_count"]),
            -int(row["size_px"]),
            float(row["tracked_x_distance_px"]),
        )
    )
    best = candidates[0]
    return {
        "label": int(best["label"]),
        "size_px": int(best["size_px"]),
        "height_rows": int(best["height_rows"]),
        "y0_local": int(best["y0_local"]),
        "y1_local": int(best["y1_local"]),
        "x0_local": int(best["x0_local"]),
        "x1_local": int(best["x1_local"]),
        "bounded_row_count": int(best["bounded_row_count"]),
        "occupied_row_count": int(best["occupied_row_count"]),
        "bounded_fraction": float(best["bounded_fraction"]),
        "median_center_x_local": None if best["median_center_x_local"] is None else float(best["median_center_x_local"]),
        "tracked_x_distance_px": float(best["tracked_x_distance_px"]),
        "touches_top": bool(best["touches_top"]),
        "touches_bottom": bool(best["touches_bottom"]),
        "touches_left": bool(best["touches_left"]),
        "touches_right": bool(best["touches_right"]),
    }


def _refine_selected_fill(
    selected_mask: np.ndarray,
    roi: dict,
    *,
    tracked_x_px: float | None,
    cutoff_y_px: int | None,
):
    final_mask = selected_mask.copy()
    seed = _find_open_bottom_interior_seed(
        selected_mask,
        roi,
        tracked_x_px=tracked_x_px,
        cutoff_y_px=cutoff_y_px,
    )
    border_info = None
    open_bottom_interior_detected = False
    fill_strategy = "binary_hole_fill"
    fill_trigger_source = "none"
    row_fill_added_pixel_count = 0

    if seed is not None:
        border_info = _background_component_border_info(
            selected_mask == 0,
            seed_y_local=int(seed["row_local"]),
            seed_x_local=int(seed["seed_x_local"]),
        )
        open_bottom_interior_detected = bool(border_info and border_info["touches_bottom"])
        if open_bottom_interior_detected:
            fill_trigger_source = "tracked_center_gap"

    fallback_component = None
    if not open_bottom_interior_detected:
        fallback_component = _find_open_bottom_interior_component(
            selected_mask,
            roi,
            tracked_x_px=tracked_x_px,
            cutoff_y_px=cutoff_y_px,
        )
        if fallback_component is not None:
            open_bottom_interior_detected = True
            border_info = fallback_component
            fill_trigger_source = "background_component_fallback"

    if open_bottom_interior_detected:
        row_filled = _row_envelope_fill(selected_mask)
        row_fill_added_pixel_count = max(
            0,
            int(np.count_nonzero(row_filled)) - int(np.count_nonzero(selected_mask)),
        )
        final_mask = row_filled
        fill_strategy = "row_envelope_fill"

    return {
        "final_mask": final_mask,
        "fill_strategy": fill_strategy,
        "fill_trigger_source": fill_trigger_source,
        "open_bottom_interior_detected": bool(open_bottom_interior_detected),
        "row_fill_added_pixel_count": int(row_fill_added_pixel_count),
        "interior_seed": seed,
        "fallback_component": fallback_component,
        "interior_border_info": border_info,
    }


def _row_span_for_label(labels: np.ndarray, label: int, row_local: int):
    if row_local < 0 or row_local >= labels.shape[0]:
        return None
    xs = np.flatnonzero(labels[row_local] == int(label))
    if xs.size <= 0:
        return None
    return {
        "x0_local": int(xs[0]),
        "x1_local": int(xs[-1]),
        "center_x_local": float((float(xs[0]) + float(xs[-1])) / 2.0),
    }


def _component_candidates(
    mask: np.ndarray,
    roi: dict,
    *,
    tracked_x_px: float | None,
    cutoff_y_px: int,
    min_component_area_px: int,
):
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    candidates = []
    cutoff_local = max(0, min(mask.shape[0] - 1, int(cutoff_y_px) - int(roi["y0"])))
    total_component_count = max(0, int(count - 1))

    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < int(min_component_area_px):
            continue

        bbox_x_local = int(stats[label, cv2.CC_STAT_LEFT])
        bbox_y_local = int(stats[label, cv2.CC_STAT_TOP])
        bbox_w = int(stats[label, cv2.CC_STAT_WIDTH])
        bbox_h = int(stats[label, cv2.CC_STAT_HEIGHT])
        top_y_local = bbox_y_local
        bottom_y_local = bbox_y_local + bbox_h - 1

        anchor_span = None
        for delta in range(0, 9):
            candidate_rows = [cutoff_local] if delta == 0 else [cutoff_local - delta, cutoff_local + delta]
            for row_local in candidate_rows:
                if row_local < top_y_local or row_local > bottom_y_local:
                    continue
                span = _row_span_for_label(labels, label, row_local)
                if span is not None:
                    anchor_span = {
                        "row_local": int(row_local),
                        **span,
                    }
                    break
            if anchor_span is not None:
                break

        if anchor_span is None:
            anchor_span = _row_span_for_label(labels, label, top_y_local)
            if anchor_span is None:
                continue
            anchor_span["row_local"] = int(top_y_local)

        anchor_center_x_px = float(int(roi["x0"]) + float(anchor_span["center_x_local"]))
        anchor_row_y_px = int(int(roi["y0"]) + int(anchor_span["row_local"]))
        top_y_px = int(int(roi["y0"]) + top_y_local)
        bottom_y_px = int(int(roi["y0"]) + bottom_y_local)
        top_gap_px = max(0.0, float(top_y_px - int(cutoff_y_px)))

        if tracked_x_px is None:
            anchor_x_distance_px = 0.0
            tracked_inside_anchor = False
        else:
            tracked_inside_anchor = (
                float(int(roi["x0"]) + int(anchor_span["x0_local"]))
                <= float(tracked_x_px)
                <= float(int(roi["x0"]) + int(anchor_span["x1_local"]))
            )
            anchor_x_distance_px = abs(anchor_center_x_px - float(tracked_x_px))

        near_score = max(0.0, 1.0 - (top_gap_px / 14.0))
        x_score = max(0.0, 1.0 - (anchor_x_distance_px / max(18.0, float(roi["width"]) * 0.18)))
        area_score = min(1.5, float(area) / max(float(min_component_area_px * 2), 1.0))
        height_score = min(1.5, float(bbox_h) / max(float(roi["height"]) * 0.25, 1.0))
        score = (near_score * 3.0) + (x_score * 2.5) + area_score + (height_score * 0.75)
        if tracked_inside_anchor:
            score += 1.5

        candidates.append(
            {
                "label": int(label),
                "area_px": area,
                "score": float(score),
                "bbox_x_px": int(int(roi["x0"]) + bbox_x_local),
                "bbox_y_px": int(int(roi["y0"]) + bbox_y_local),
                "bbox_w_px": bbox_w,
                "bbox_h_px": bbox_h,
                "top_y_px": top_y_px,
                "bottom_y_px": bottom_y_px,
                "anchor_row_y_px": anchor_row_y_px,
                "anchor_center_x_px": anchor_center_x_px,
                "centroid_x_px": float(int(roi["x0"]) + float(centroids[label][0])),
                "centroid_y_px": float(int(roi["y0"]) + float(centroids[label][1])),
            }
        )

    return {
        "labels": labels,
        "total_component_count": total_component_count,
        "candidates": candidates,
    }


def _select_primary_component(
    mask: np.ndarray,
    roi: dict,
    *,
    tracked_x_px: float | None,
    cutoff_y_px: int,
    min_component_area_px: int,
):
    component_info = _component_candidates(
        mask,
        roi,
        tracked_x_px=tracked_x_px,
        cutoff_y_px=cutoff_y_px,
        min_component_area_px=min_component_area_px,
    )
    candidates = list(component_info["candidates"])
    if not candidates:
        return {
            "labels": component_info["labels"],
            "connected_component_count": int(component_info["total_component_count"]),
            "candidate_component_count": 0,
            "candidates": [],
            "selected_component": None,
            "selected_mask": np.zeros_like(mask),
        }

    selected = max(candidates, key=lambda item: (float(item["score"]), int(item["area_px"])))
    selected_mask = np.where(component_info["labels"] == int(selected["label"]), 255, 0).astype(np.uint8)
    return {
        "labels": component_info["labels"],
        "connected_component_count": int(component_info["total_component_count"]),
        "candidate_component_count": int(len(candidates)),
        "candidates": candidates,
        "selected_component": selected,
        "selected_mask": selected_mask,
    }


def _mask_for_label(labels: np.ndarray, label: int):
    return np.where(labels == int(label), 255, 0).astype(np.uint8)


def _accepted_detached_components(selection: dict, roi: dict, *, cutoff_y_px: int):
    selected = selection.get("selected_component")
    if selected is None:
        return []

    center_tolerance_px = max(32.0, float(roi["width"]) * 0.12)
    accepted = []
    for candidate in selection.get("candidates", []):
        if int(candidate["label"]) == int(selected["label"]):
            continue
        if int(candidate["top_y_px"]) < int(cutoff_y_px) + 24:
            continue
        if abs(float(candidate["anchor_center_x_px"]) - float(selected["anchor_center_x_px"])) > center_tolerance_px:
            continue
        accepted.append(dict(candidate))

    accepted.sort(
        key=lambda item: (
            int(item["top_y_px"]),
            float(item["anchor_center_x_px"]),
            -int(item["area_px"]),
        )
    )
    for rank, component in enumerate(accepted, start=1):
        component["component_id"] = f"detached_{rank:02d}"
        component["component_role"] = "detached_accepted"
        component["component_rank"] = int(rank)
    return accepted


def _trace_edges(
    selected_mask: np.ndarray,
    roi: dict,
    frame_row: dict,
    *,
    component_id: str = "attached_primary",
    component_role: str = "attached_primary",
    component_rank: int = 0,
):
    edge_rows = []
    for row_local in np.flatnonzero(np.any(selected_mask > 0, axis=1)):
        xs = np.flatnonzero(selected_mask[row_local] > 0)
        if xs.size <= 0:
            continue
        x_left_px = int(int(roi["x0"]) + int(xs[0]))
        x_right_px = int(int(roi["x0"]) + int(xs[-1]))
        width_px = int(x_right_px - x_left_px + 1)
        edge_rows.append(
            {
                "run_id": frame_row.get("run_id"),
                "capture_id": frame_row.get("capture_id"),
                "capture_index": _int_or_none(frame_row.get("capture_index")),
                "flash_delay_us": _int_or_none(frame_row.get("flash_delay_us")),
                "component_id": str(component_id),
                "component_role": str(component_role),
                "component_rank": int(component_rank),
                "y_px": int(int(roi["y0"]) + int(row_local)),
                "x_left_px": x_left_px,
                "x_right_px": x_right_px,
                "width_px": width_px,
                "center_x_px": float((float(x_left_px) + float(x_right_px)) / 2.0),
            }
        )
    return edge_rows


def _resize_to_height(image: np.ndarray, target_height: int) -> np.ndarray:
    height, width = image.shape[:2]
    if height == target_height:
        return image
    scale = float(target_height) / float(height)
    target_width = max(1, int(round(width * scale)))
    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _draw_label(image: np.ndarray, text: str):
    cv2.putText(
        image,
        text,
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.60,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def _mask_panel(mask: np.ndarray, label: str):
    panel = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    panel[mask > 0] = (255, 255, 255)
    return _draw_label(panel, label)


def _component_color(component_role: str):
    if str(component_role) == "attached_primary":
        return (0, 255, 0)
    return (0, 191, 255)


def _draw_nozzle_context(
    image: np.ndarray,
    *,
    nozzle_x_px: float | None,
    nozzle_y_px: float | None,
    cutoff_y_px: int | None,
    x0_px: int,
    x1_px: int,
):
    if cutoff_y_px is not None:
        cv2.line(image, (int(x0_px), int(cutoff_y_px)), (int(x1_px), int(cutoff_y_px)), (0, 0, 255), 2)
    if nozzle_x_px is not None and nozzle_y_px is not None:
        cv2.circle(image, (int(round(float(nozzle_x_px))), int(round(float(nozzle_y_px)))), 5, (255, 0, 255), -1)
    return image


def _accepted_mask_panel(roi_shape, accepted_components: list[dict], label: str):
    panel = np.zeros((int(roi_shape[0]), int(roi_shape[1]), 3), dtype=np.uint8)
    for component in accepted_components:
        final_mask = component.get("final_mask")
        if final_mask is None:
            continue
        panel[final_mask > 0] = _component_color(component.get("component_role", "detached_accepted"))
    return _draw_label(panel, label)


def _contour_overlay(
    roi_gray: np.ndarray,
    accepted_components: list[dict],
    *,
    roi: dict,
    tracked_row: dict,
    cutoff_y_px: int | None,
):
    overlay = cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR)
    for component in accepted_components:
        component_mask = component.get("final_mask")
        component_edges = component.get("edge_rows") or []
        color = _component_color(component.get("component_role", "detached_accepted"))

        if component_mask is not None and np.any(component_mask > 0):
            contours, _hierarchy = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                cv2.drawContours(overlay, contours, -1, color, 2)

        if component_edges:
            left_points = np.array(
                [
                    [int(row["x_left_px"]) - int(roi["x0"]), int(row["y_px"]) - int(roi["y0"])]
                    for row in component_edges
                ],
                dtype=np.int32,
            )
            right_points = np.array(
                [
                    [int(row["x_right_px"]) - int(roi["x0"]), int(row["y_px"]) - int(roi["y0"])]
                    for row in component_edges
                ],
                dtype=np.int32,
            )
            if len(left_points) >= 2:
                cv2.polylines(overlay, [left_points.reshape((-1, 1, 2))], False, color, 1)
            if len(right_points) >= 2:
                cv2.polylines(overlay, [right_points.reshape((-1, 1, 2))], False, color, 1)

    overlay = _draw_nozzle_context(
        overlay,
        nozzle_x_px=None if tracked_row.get("tracked_nozzle_x_px") is None else float(tracked_row["tracked_nozzle_x_px"]) - float(roi["x0"]),
        nozzle_y_px=None if tracked_row.get("tracked_nozzle_y_px") is None else float(tracked_row["tracked_nozzle_y_px"]) - float(roi["y0"]),
        cutoff_y_px=None if cutoff_y_px is None else int(cutoff_y_px) - int(roi["y0"]),
        x0_px=0,
        x1_px=max(0, roi_gray.shape[1] - 1),
    )
    return _draw_label(overlay, "contour + edge traces")


def _build_sample_panel(
    gray: np.ndarray,
    roi: dict,
    corridor: dict,
    tracked_row: dict,
    metric_row: dict,
    raw_mask: np.ndarray,
    accepted_components: list[dict],
):
    roi_gray = gray[roi["y0"] : roi["y1"], roi["x0"] : roi["x1"]]
    cutoff_y_px = _int_or_none(metric_row.get("cutoff_y_px"))

    full = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(full, (int(roi["x0"]), int(roi["y0"])), (int(roi["x1"]), int(roi["y1"])), (0, 255, 255), 2)
    cv2.line(full, (int(corridor["x0"]), int(roi["y0"])), (int(corridor["x0"]), int(roi["y1"]) - 1), (255, 255, 0), 1)
    cv2.line(full, (int(corridor["x1"]) - 1, int(roi["y0"])), (int(corridor["x1"]) - 1, int(roi["y1"]) - 1), (255, 255, 0), 1)
    full = _draw_nozzle_context(
        full,
        nozzle_x_px=tracked_row.get("tracked_nozzle_x_px"),
        nozzle_y_px=tracked_row.get("tracked_nozzle_y_px"),
        cutoff_y_px=cutoff_y_px,
        x0_px=int(roi["x0"]),
        x1_px=max(int(roi["x0"]), int(roi["x1"]) - 1),
    )
    full = _draw_label(
        full,
        (
            f"frame {metric_row.get('capture_index')}  "
            f"status={metric_row.get('silhouette_status')}  "
            f"mode={metric_row.get('final_mode')}  "
            f"conf={float(metric_row.get('tracked_confidence') or 0.0):.2f}"
        ),
    )

    roi_panel = cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR)
    roi_panel = _draw_nozzle_context(
        roi_panel,
        nozzle_x_px=None if tracked_row.get("tracked_nozzle_x_px") is None else float(tracked_row["tracked_nozzle_x_px"]) - float(roi["x0"]),
        nozzle_y_px=None if tracked_row.get("tracked_nozzle_y_px") is None else float(tracked_row["tracked_nozzle_y_px"]) - float(roi["y0"]),
        cutoff_y_px=None if cutoff_y_px is None else int(cutoff_y_px) - int(roi["y0"]),
        x0_px=0,
        x1_px=max(0, roi_gray.shape[1] - 1),
    )
    roi_panel = _draw_label(roi_panel, "grayscale ROI")

    contour_panel = _contour_overlay(
        roi_gray,
        accepted_components,
        roi=roi,
        tracked_row=tracked_row,
        cutoff_y_px=cutoff_y_px,
    )

    target_height = 280
    row_images = [
        _resize_to_height(full, target_height),
        _resize_to_height(roi_panel, target_height),
        _resize_to_height(_mask_panel(raw_mask, "raw threshold mask"), target_height),
        _resize_to_height(_accepted_mask_panel(raw_mask.shape, accepted_components, "accepted fluid mask"), target_height),
        _resize_to_height(contour_panel, target_height),
    ]
    return cv2.hconcat(row_images)


def _component_metric_row(frame_row: dict, component: dict, edge_rows: list[dict], fill_refinement: dict):
    valid_row_count = len(edge_rows)
    max_width_px = max((int(row["width_px"]) for row in edge_rows), default=None)
    final_mask = component.get("final_mask")
    return {
        "run_id": frame_row.get("run_id"),
        "capture_id": frame_row.get("capture_id"),
        "capture_index": _int_or_none(frame_row.get("capture_index")),
        "flash_delay_us": _int_or_none(frame_row.get("flash_delay_us")),
        "component_id": component.get("component_id"),
        "component_role": component.get("component_role"),
        "component_rank": int(component.get("component_rank") or 0),
        "component_area_px": int(np.count_nonzero(final_mask)) if final_mask is not None else 0,
        "component_score": None if component.get("score") is None else float(component["score"]),
        "bbox_x_px": int(component["bbox_x_px"]),
        "bbox_y_px": int(component["bbox_y_px"]),
        "bbox_w_px": int(component["bbox_w_px"]),
        "bbox_h_px": int(component["bbox_h_px"]),
        "top_y_px": int(component["top_y_px"]),
        "bottom_y_px": int(component["bottom_y_px"]),
        "anchor_row_y_px": int(component["anchor_row_y_px"]),
        "anchor_center_x_px": float(component["anchor_center_x_px"]),
        "fill_strategy": fill_refinement.get("fill_strategy"),
        "fill_trigger_source": fill_refinement.get("fill_trigger_source"),
        "open_bottom_interior_detected": bool(fill_refinement.get("open_bottom_interior_detected")),
        "row_fill_added_pixel_count": int(fill_refinement.get("row_fill_added_pixel_count") or 0),
        "valid_row_count": valid_row_count,
        "first_valid_y_px": None if not edge_rows else int(edge_rows[0]["y_px"]),
        "last_valid_y_px": None if not edge_rows else int(edge_rows[-1]["y_px"]),
        "max_width_px": max_width_px,
    }


def _silhouette_metric_row(
    run_id: str,
    frame_row: dict,
    tracked_row: dict,
    *,
    roi: dict,
    corridor: dict,
    threshold_value: float | None,
    cutoff_y_px: int | None,
    raw_mask: np.ndarray,
    final_selected_mask: np.ndarray,
    selection: dict,
    fill_refinement: dict,
    edge_rows: list[dict],
    accepted_components: list[dict],
    silhouette_status: str,
    failure_reason: str | None,
):
    selected = selection.get("selected_component")
    valid_row_count = len(edge_rows)
    max_width_px = max((int(row["width_px"]) for row in edge_rows), default=None)
    selected_component_area_px = (
        None if selected is None else int(np.count_nonzero(final_selected_mask))
    )
    accepted_component_count = int(len(accepted_components))
    accepted_detached_component_count = int(
        sum(1 for component in accepted_components if component.get("component_role") == "detached_accepted")
    )
    attached_component_area_px = None if selected is None else int(np.count_nonzero(final_selected_mask))
    detached_component_area_px_total = int(
        sum(
            int(np.count_nonzero(component.get("final_mask")))
            for component in accepted_components
            if component.get("component_role") == "detached_accepted" and component.get("final_mask") is not None
        )
    )
    accepted_total_area_px = int(
        sum(
            int(np.count_nonzero(component.get("final_mask")))
            for component in accepted_components
            if component.get("final_mask") is not None
        )
    )
    return {
        "run_id": run_id,
        "capture_id": frame_row.get("capture_id"),
        "capture_index": _int_or_none(frame_row.get("capture_index")),
        "image_relpath": frame_row.get("image_relpath"),
        "image_exists": bool(frame_row.get("image_exists")),
        "captured_at_utc": frame_row.get("captured_at_utc"),
        "flash_delay_us": _int_or_none(frame_row.get("flash_delay_us")),
        "delay_from_emergence_us": _int_or_none(frame_row.get("delay_from_emergence_us")),
        "tracked_nozzle_x_px": tracked_row.get("tracked_nozzle_x_px"),
        "tracked_nozzle_y_px": tracked_row.get("tracked_nozzle_y_px"),
        "tracked_confidence": tracked_row.get("tracked_confidence"),
        "raw_mode": tracked_row.get("raw_mode"),
        "final_mode": tracked_row.get("final_mode"),
        "segment_id": _int_or_none(tracked_row.get("segment_id")),
        "shift_event_before": bool(tracked_row.get("shift_event_before")),
        "input_policy": INPUT_POLICY,
        "threshold_method": "otsu_dark",
        "threshold_value": None if threshold_value is None else float(threshold_value),
        "roi_x0": int(roi["x0"]),
        "roi_y0": int(roi["y0"]),
        "roi_x1": int(roi["x1"]),
        "roi_y1": int(roi["y1"]),
        "roi_width": int(roi["width"]),
        "roi_height": int(roi["height"]),
        "corridor_x0": int(corridor["x0"]),
        "corridor_x1": int(corridor["x1"]),
        "corridor_width": int(corridor["width"]),
        "nozzle_guard_px": None if cutoff_y_px is None or tracked_row.get("tracked_nozzle_y_px") is None else int(round(float(cutoff_y_px) - float(tracked_row["tracked_nozzle_y_px"]))),
        "cutoff_y_px": cutoff_y_px,
        "raw_dark_pixel_count": int(np.count_nonzero(raw_mask)),
        "raw_dark_fraction": float(np.count_nonzero(raw_mask)) / float(raw_mask.size) if raw_mask.size else 0.0,
        "filled_pixel_count": int(np.count_nonzero(final_selected_mask)),
        "filled_fraction": float(np.count_nonzero(final_selected_mask)) / float(final_selected_mask.size) if final_selected_mask.size else 0.0,
        "fill_strategy": fill_refinement.get("fill_strategy"),
        "fill_trigger_source": fill_refinement.get("fill_trigger_source"),
        "open_bottom_interior_detected": bool(fill_refinement.get("open_bottom_interior_detected")),
        "row_fill_added_pixel_count": int(fill_refinement.get("row_fill_added_pixel_count") or 0),
        "accepted_component_count": accepted_component_count,
        "accepted_detached_component_count": accepted_detached_component_count,
        "attached_component_area_px": attached_component_area_px,
        "detached_component_area_px_total": detached_component_area_px_total,
        "accepted_total_area_px": accepted_total_area_px,
        "connected_component_count": int(selection.get("connected_component_count") or 0),
        "candidate_component_count": int(selection.get("candidate_component_count") or 0),
        "selected_component_area_px": selected_component_area_px,
        "selected_component_score": None if selected is None else float(selected["score"]),
        "selected_component_bbox_x_px": None if selected is None else int(selected["bbox_x_px"]),
        "selected_component_bbox_y_px": None if selected is None else int(selected["bbox_y_px"]),
        "selected_component_bbox_w_px": None if selected is None else int(selected["bbox_w_px"]),
        "selected_component_bbox_h_px": None if selected is None else int(selected["bbox_h_px"]),
        "selected_component_top_y_px": None if selected is None else int(selected["top_y_px"]),
        "selected_component_bottom_y_px": None if selected is None else int(selected["bottom_y_px"]),
        "selected_anchor_row_y_px": None if selected is None else int(selected["anchor_row_y_px"]),
        "selected_anchor_center_x_px": None if selected is None else float(selected["anchor_center_x_px"]),
        "silhouette_status": str(silhouette_status),
        "failure_reason": _clean_text(failure_reason),
        "valid_row_count": valid_row_count,
        "first_valid_y_px": None if not edge_rows else int(edge_rows[0]["y_px"]),
        "last_valid_y_px": None if not edge_rows else int(edge_rows[-1]["y_px"]),
        "max_width_px": max_width_px,
        "sample_frame": False,
    }


def _summary_from_metric_rows(metric_rows: list[dict], component_rows: list[dict], edge_rows: list[dict]):
    status_counts = {}
    fill_strategy_counts = {}
    valid_row_counts = []
    selected_areas = []
    accepted_component_counts = []
    accepted_detached_component_counts = []
    for row in metric_rows:
        status = _clean_text(row.get("silhouette_status")) or "unknown"
        status_counts[status] = int(status_counts.get(status, 0) + 1)
        fill_strategy = _clean_text(row.get("fill_strategy")) or "unknown"
        fill_strategy_counts[fill_strategy] = int(fill_strategy_counts.get(fill_strategy, 0) + 1)
        if row.get("valid_row_count") is not None:
            valid_row_counts.append(int(row["valid_row_count"]))
        if row.get("selected_component_area_px") is not None:
            selected_areas.append(int(row["selected_component_area_px"]))
        if row.get("accepted_component_count") is not None:
            accepted_component_counts.append(int(row["accepted_component_count"]))
        if row.get("accepted_detached_component_count") is not None:
            accepted_detached_component_counts.append(int(row["accepted_detached_component_count"]))
    ok_frames = sum(1 for row in metric_rows if _clean_text(row.get("silhouette_status")) == "ok")
    return {
        "frame_count": len(metric_rows),
        "ok_frame_count": ok_frames,
        "status_counts": status_counts,
        "fill_strategy_counts": fill_strategy_counts,
        "component_row_count": len(component_rows),
        "open_bottom_interior_detected_count": sum(
            1 for row in metric_rows if bool(row.get("open_bottom_interior_detected"))
        ),
        "edge_row_count": len(edge_rows),
        "accepted_component_count_max": max(accepted_component_counts) if accepted_component_counts else None,
        "accepted_detached_component_count_max": max(accepted_detached_component_counts) if accepted_detached_component_counts else None,
        "valid_row_count_min": min(valid_row_counts) if valid_row_counts else None,
        "valid_row_count_max": max(valid_row_counts) if valid_row_counts else None,
        "selected_component_area_min": min(selected_areas) if selected_areas else None,
        "selected_component_area_max": max(selected_areas) if selected_areas else None,
    }


def _analyze_accepted_component(
    frame_row: dict,
    roi: dict,
    component: dict,
    component_mask: np.ndarray,
    *,
    tracked_x_px: float | None,
    cutoff_y_px: int,
):
    fill_refinement = _refine_selected_fill(
        component_mask,
        roi,
        tracked_x_px=tracked_x_px,
        cutoff_y_px=int(cutoff_y_px),
    )
    final_mask = fill_refinement["final_mask"]
    edge_rows = _trace_edges(
        final_mask,
        roi,
        frame_row,
        component_id=str(component["component_id"]),
        component_role=str(component["component_role"]),
        component_rank=int(component["component_rank"]),
    )
    component_state = dict(component)
    component_state["final_mask"] = final_mask
    component_state["fill_refinement"] = fill_refinement
    component_state["edge_rows"] = edge_rows
    component_state["component_row"] = _component_metric_row(
        frame_row,
        component_state,
        edge_rows,
        fill_refinement,
    )
    return component_state


def _analyze_stage3_gray(
    run_id: str,
    frame_row: dict,
    tracked_row: dict,
    gray: np.ndarray,
    *,
    roi_width_frac: float,
    roi_top_frac: float,
    roi_bottom_frac: float,
    corridor_width_frac: float,
    nozzle_guard_px: int,
    min_component_area_px: int,
):
    gray = _coerce_gray_image(gray)
    tracked_x_px = tracked_row.get("tracked_nozzle_x_px")
    tracked_y_px = tracked_row.get("tracked_nozzle_y_px")
    roi = _dynamic_roi_bounds(
        gray.shape,
        tracked_x_px=tracked_x_px if tracked_x_px is not None else None,
        roi_width_frac=roi_width_frac,
        roi_top_frac=roi_top_frac,
        roi_bottom_frac=roi_bottom_frac,
    )
    corridor = _corridor_bounds(
        roi,
        tracked_x_px=tracked_x_px if tracked_x_px is not None else None,
        corridor_width_frac=corridor_width_frac,
    )

    threshold_value = None
    raw_mask = np.zeros((roi["height"], roi["width"]), dtype=np.uint8)
    filled_mask = np.zeros_like(raw_mask)
    final_selected_mask = np.zeros_like(raw_mask)
    selection = {
        "connected_component_count": 0,
        "candidate_component_count": 0,
        "candidates": [],
        "selected_component": None,
        "selected_mask": np.zeros_like(raw_mask),
    }
    fill_refinement = {
        "final_mask": final_selected_mask,
        "fill_strategy": "binary_hole_fill",
        "fill_trigger_source": "none",
        "open_bottom_interior_detected": False,
        "row_fill_added_pixel_count": 0,
        "interior_seed": None,
        "fallback_component": None,
        "interior_border_info": None,
    }
    attached_edge_rows = []
    accepted_components = []
    component_rows = []
    edge_rows = []

    if tracked_x_px is None or tracked_y_px is None:
        silhouette_status = "missing_nozzle_track"
        failure_reason = "tracked nozzle location unavailable"
        cutoff_y_px = None
    else:
        cutoff_y_px = int(np.floor(float(tracked_y_px) + float(nozzle_guard_px)))
        roi_gray = gray[roi["y0"] : roi["y1"], roi["x0"] : roi["x1"]]
        threshold_value, raw_mask = _threshold_roi(roi_gray)
        raw_mask = _apply_corridor_mask(raw_mask, roi, corridor)
        raw_mask = _apply_nozzle_cutoff(raw_mask, roi, cutoff_y_px=cutoff_y_px)
        filled_mask = _clean_filled_mask(raw_mask)

        if not np.any(filled_mask > 0):
            silhouette_status = "empty_mask"
            failure_reason = "no pixels remain after thresholding and cutoff"
        else:
            selection = _select_primary_component(
                filled_mask,
                roi,
                tracked_x_px=float(tracked_x_px),
                cutoff_y_px=int(cutoff_y_px),
                min_component_area_px=min_component_area_px,
            )
            if selection["selected_component"] is None:
                silhouette_status = "no_component_selected"
                failure_reason = "no eligible component matched the nozzle-anchored selector"
            else:
                attached_component = dict(selection["selected_component"])
                attached_component["component_id"] = "attached_primary"
                attached_component["component_role"] = "attached_primary"
                attached_component["component_rank"] = 0
                attached_state = _analyze_accepted_component(
                    frame_row,
                    roi,
                    attached_component,
                    selection["selected_mask"],
                    tracked_x_px=float(tracked_x_px),
                    cutoff_y_px=int(cutoff_y_px),
                )
                fill_refinement = attached_state["fill_refinement"]
                final_selected_mask = attached_state["final_mask"]
                attached_edge_rows = list(attached_state["edge_rows"])
                if not attached_edge_rows:
                    silhouette_status = "no_valid_rows"
                    failure_reason = "selected component did not produce row-wise edge traces"
                else:
                    accepted_components.append(attached_state)
                    detached_components = _accepted_detached_components(
                        selection,
                        roi,
                        cutoff_y_px=int(cutoff_y_px),
                    )
                    for component in detached_components:
                        detached_mask = _mask_for_label(selection["labels"], int(component["label"]))
                        accepted_components.append(
                            _analyze_accepted_component(
                                frame_row,
                                roi,
                                component,
                                detached_mask,
                                tracked_x_px=float(component["anchor_center_x_px"]),
                                cutoff_y_px=int(cutoff_y_px),
                            )
                        )
                    component_rows = [component["component_row"] for component in accepted_components]
                    edge_rows = [
                        row
                        for component in accepted_components
                        for row in component["edge_rows"]
                    ]
                    silhouette_status = "ok"
                    failure_reason = None

    metric_row = _silhouette_metric_row(
        run_id,
        frame_row,
        tracked_row,
        roi=roi,
        corridor=corridor,
        threshold_value=threshold_value,
        cutoff_y_px=cutoff_y_px,
        raw_mask=raw_mask,
        final_selected_mask=final_selected_mask if selection.get("selected_component") is not None else filled_mask,
        selection=selection,
        fill_refinement=fill_refinement,
        edge_rows=attached_edge_rows,
        accepted_components=accepted_components,
        silhouette_status=silhouette_status,
        failure_reason=failure_reason,
    )
    return {
        "gray": gray,
        "roi": roi,
        "corridor": corridor,
        "raw_mask": raw_mask,
        "metric_row": metric_row,
        "component_rows": component_rows,
        "edge_rows": edge_rows,
        "accepted_components": accepted_components,
        "tracked_row": tracked_row,
    }


def _analyze_stage3_frame(
    run_id: str,
    frame_row: dict,
    tracked_row: dict,
    *,
    roi_width_frac: float,
    roi_top_frac: float,
    roi_bottom_frac: float,
    corridor_width_frac: float,
    nozzle_guard_px: int,
    min_component_area_px: int,
):
    image_path = Path(str(frame_row["image_abs_path"]))
    gray = _load_gray_image(image_path)
    analyzed = _analyze_stage3_gray(
        run_id,
        frame_row,
        tracked_row,
        gray,
        roi_width_frac=roi_width_frac,
        roi_top_frac=roi_top_frac,
        roi_bottom_frac=roi_bottom_frac,
        corridor_width_frac=corridor_width_frac,
        nozzle_guard_px=nozzle_guard_px,
        min_component_area_px=min_component_area_px,
    )
    analyzed["image_path"] = str(image_path)
    return analyzed


def _build_stage3_run(
    run_id: str,
    frame_rows: list[dict],
    *,
    sample_count: int,
    extra_frame_indices: list[int] | None,
    search_width_frac: float,
    search_top_frac: float,
    search_bottom_frac: float,
    blur_sigma: float,
    residual_threshold: int,
    shift_threshold_px: float,
    confidence_threshold: float,
    roi_width_frac: float,
    roi_top_frac: float,
    roi_bottom_frac: float,
    corridor_width_frac: float,
    nozzle_guard_px: int,
    min_component_area_px: int,
):
    stage2_run = _build_stage2_run(
        run_id,
        frame_rows,
        search_width_frac=search_width_frac,
        search_top_frac=search_top_frac,
        search_bottom_frac=search_bottom_frac,
        blur_sigma=blur_sigma,
        residual_scale=2.5,
        residual_threshold=residual_threshold,
        min_area_px=120,
        top_band_slack_px=14,
        shift_threshold_px=shift_threshold_px,
        confidence_threshold=confidence_threshold,
    )
    tracked_rows = list(stage2_run["tracked_rows"])
    shift_events = list(stage2_run["shift_events"])
    sample_indices = set(
        _sample_indices(
            len(frame_rows),
            sample_count=sample_count,
            extra_frame_indices=extra_frame_indices,
        )
    )
    sample_indices.update(
        int(event["previous_capture_index"])
        for event in shift_events
        if event.get("previous_capture_index")
    )
    sample_indices.update(
        int(event["next_capture_index"])
        for event in shift_events
        if event.get("next_capture_index")
    )

    metric_rows = []
    component_rows = []
    edge_rows = []
    sample_inputs = {}

    for frame_row, tracked_row in zip(frame_rows, tracked_rows):
        analysis = _analyze_stage3_frame(
            run_id,
            frame_row,
            tracked_row,
            roi_width_frac=roi_width_frac,
            roi_top_frac=roi_top_frac,
            roi_bottom_frac=roi_bottom_frac,
            corridor_width_frac=corridor_width_frac,
            nozzle_guard_px=nozzle_guard_px,
            min_component_area_px=min_component_area_px,
        )
        metric_row = analysis["metric_row"]
        capture_index = _int_or_none(metric_row.get("capture_index")) or 0
        if capture_index in sample_indices:
            metric_row["sample_frame"] = True
            sample_inputs[capture_index] = {
                "image_path": analysis["image_path"],
                "roi": analysis["roi"],
                "corridor": analysis["corridor"],
                "tracked_row": tracked_row,
                "metric_row": metric_row,
                "raw_mask": analysis["raw_mask"],
                "accepted_components": analysis["accepted_components"],
            }
        metric_rows.append(metric_row)
        component_rows.extend(analysis["component_rows"])
        edge_rows.extend(analysis["edge_rows"])

    return {
        "tracked_rows": tracked_rows,
        "shift_events": shift_events,
        "sample_indices": sorted(sample_indices),
        "metric_rows": metric_rows,
        "component_rows": component_rows,
        "edge_rows": edge_rows,
        "sample_inputs": sample_inputs,
    }


def export_stage3_silhouette(
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
    residual_threshold: int = 18,
    shift_threshold_px: float = 6.0,
    confidence_threshold: float = 0.55,
    roi_width_frac: float = 0.35,
    roi_top_frac: float = 0.10,
    roi_bottom_frac: float = 1.0,
    corridor_width_frac: float = 0.70,
    nozzle_guard_px: int = 2,
    min_component_area_px: int = 120,
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
        stage3_run = _build_stage3_run(
            run_id,
            frame_rows,
            sample_count=sample_count,
            extra_frame_indices=extra_frame_indices,
            search_width_frac=search_width_frac,
            search_top_frac=search_top_frac,
            search_bottom_frac=search_bottom_frac,
            blur_sigma=blur_sigma,
            residual_threshold=residual_threshold,
            shift_threshold_px=shift_threshold_px,
            confidence_threshold=confidence_threshold,
            roi_width_frac=roi_width_frac,
            roi_top_frac=roi_top_frac,
            roi_bottom_frac=roi_bottom_frac,
            corridor_width_frac=corridor_width_frac,
            nozzle_guard_px=nozzle_guard_px,
            min_component_area_px=min_component_area_px,
        )
        shift_events = list(stage3_run["shift_events"])
        sample_indices = set(stage3_run["sample_indices"])

        stage_dir = output_path / "runs" / run_id / SILHOUETTE_STAGE_DIRNAME
        stage_dir.mkdir(parents=True, exist_ok=True)
        sample_dir = stage_dir / "samples"
        if sample_dir.exists():
            for stale_panel in sample_dir.glob("*.png"):
                stale_panel.unlink()
        else:
            sample_dir.mkdir(parents=True, exist_ok=True)

        metric_rows = list(stage3_run["metric_rows"])
        component_rows = list(stage3_run["component_rows"])
        edge_rows = list(stage3_run["edge_rows"])
        sample_panels = []
        sample_panel_paths = []

        for capture_index in stage3_run["sample_indices"]:
            sample_input = stage3_run["sample_inputs"].get(int(capture_index))
            if sample_input is None:
                continue
            gray = _load_gray_image(Path(str(sample_input["image_path"])))
            panel = _build_sample_panel(
                gray,
                sample_input["roi"],
                sample_input["corridor"],
                sample_input["tracked_row"],
                sample_input["metric_row"],
                sample_input["raw_mask"],
                sample_input["accepted_components"],
            )
            panel_path = sample_dir / f"frame_{int(capture_index):03d}_panel.png"
            cv2.imwrite(str(panel_path), panel)
            sample_panels.append(panel)
            sample_panel_paths.append(str(panel_path))

        metrics_csv = stage_dir / "silhouette_metrics.csv"
        component_csv = stage_dir / "component_metrics.csv"
        edge_csv = stage_dir / "edge_traces.csv"
        edge_json = stage_dir / "edge_traces.json"
        summary_json = stage_dir / "silhouette_manifest.json"
        contact_sheet_png = stage_dir / "sample_contact_sheet.png"

        _write_csv(metrics_csv, _preferred_columns(metric_rows, SILHOUETTE_METRIC_COLUMNS), metric_rows)
        _write_csv(component_csv, _preferred_columns(component_rows, COMPONENT_METRIC_COLUMNS), component_rows)
        _write_csv(edge_csv, _preferred_columns(edge_rows, EDGE_TRACE_COLUMNS), edge_rows)
        _write_json(
            edge_json,
            {
                "schema_version": 1,
                "stage": "silhouette",
                "run_id": run_id,
                "row_count": len(edge_rows),
                "rows": edge_rows,
            },
        )
        if sample_panels:
            cv2.imwrite(str(contact_sheet_png), cv2.vconcat(sample_panels))

        summary = {
            "schema_version": 1,
            "stage": "silhouette",
            "run_id": run_id,
            "run_dir": run_row["run_dir"],
            "input_policy": INPUT_POLICY,
            "nozzle_tracking": {
                "search_width_frac": float(search_width_frac),
                "search_top_frac": float(search_top_frac),
                "search_bottom_frac": float(search_bottom_frac),
                "blur_sigma": float(blur_sigma),
                "residual_threshold": int(residual_threshold),
                "shift_threshold_px": float(shift_threshold_px),
                "confidence_threshold": float(confidence_threshold),
            },
            "roi": {
                "width_frac": float(roi_width_frac),
                "top_frac": float(roi_top_frac),
                "bottom_frac": float(roi_bottom_frac),
                "corridor_width_frac": float(corridor_width_frac),
            },
            "nozzle_guard_px": int(nozzle_guard_px),
            "min_component_area_px": int(min_component_area_px),
            "sample_capture_indices": sorted(sample_indices),
            "sample_panel_paths": sample_panel_paths,
            "outputs": {
                "silhouette_metrics_csv": str(metrics_csv),
                "component_metrics_csv": str(component_csv),
                "edge_traces_csv": str(edge_csv),
                "edge_traces_json": str(edge_json),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
            },
            "summary": _summary_from_metric_rows(metric_rows, component_rows, edge_rows),
            "shift_events": shift_events,
        }
        _write_json(summary_json, summary)
        run_manifests.append(
            {
                "run_id": run_id,
                "run_dir": run_row["run_dir"],
                "silhouette_metrics_csv": str(metrics_csv),
                "component_metrics_csv": str(component_csv),
                "edge_traces_csv": str(edge_csv),
                "edge_traces_json": str(edge_json),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
                "frame_count": len(metric_rows),
                "component_row_count": len(component_rows),
                "edge_row_count": len(edge_rows),
                "sample_frame_count": len(sample_indices),
            }
        )

    manifest = {
        "schema_version": 1,
        "stage": "silhouette",
        "experiment_root": inventory["experiment_root"],
        "output_root": str(output_path),
        "input_policy": INPUT_POLICY,
        "selected_run_count": len(run_manifests),
        "run_ids": [row["run_id"] for row in run_manifests],
        "search_width_frac": float(search_width_frac),
        "search_top_frac": float(search_top_frac),
        "search_bottom_frac": float(search_bottom_frac),
        "blur_sigma": float(blur_sigma),
        "residual_threshold": int(residual_threshold),
        "shift_threshold_px": float(shift_threshold_px),
        "confidence_threshold": float(confidence_threshold),
        "roi_width_frac": float(roi_width_frac),
        "roi_top_frac": float(roi_top_frac),
        "roi_bottom_frac": float(roi_bottom_frac),
        "corridor_width_frac": float(corridor_width_frac),
        "nozzle_guard_px": int(nozzle_guard_px),
        "min_component_area_px": int(min_component_area_px),
        "sample_count": int(sample_count),
        "extra_frame_indices": list(extra_frame_indices or []),
        "runs": run_manifests,
    }
    manifest_path = output_path / "silhouette_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest
