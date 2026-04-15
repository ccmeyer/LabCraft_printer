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
) -> dict:
    tracked_nozzle_y_px = stage3_metric_row.get("tracked_nozzle_y_px")
    if tracked_nozzle_y_px is None:
        return {
            "attached_width_px": None,
            "width_valid_row_count": 0,
            "band_y0_px": None,
            "band_y1_px": None,
        }

    band_y0_px = int(np.floor(float(tracked_nozzle_y_px) + float(near_nozzle_band_top_px)))
    band_y1_px = int(band_y0_px + int(near_nozzle_band_height_px))
    widths = [
        int(row["width_px"])
        for row in list(attached_edge_rows or [])
        if band_y0_px <= int(row["y_px"]) < band_y1_px
    ]
    valid_row_count = int(len(widths))
    if valid_row_count < int(min_band_valid_rows):
        return {
            "attached_width_px": None,
            "width_valid_row_count": valid_row_count,
            "band_y0_px": band_y0_px,
            "band_y1_px": band_y1_px,
        }

    return {
        "attached_width_px": float(np.median(np.asarray(widths, dtype=float))),
        "width_valid_row_count": valid_row_count,
        "band_y0_px": band_y0_px,
        "band_y1_px": band_y1_px,
    }


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
        band_y1_px=width_metrics.get("band_y1_px"),
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
    metrics = _centerline_residual_metrics(
        attached_edge_rows,
        lower_fraction=float(lower_row_fraction),
    )
    row_count = int(metrics.get("row_count") or 0)
    span_px = metrics.get("span_px")
    rms_px = metrics.get("rms_px")
    reasons = []
    geometry_ok = None
    if geometry_assessable:
        if row_count >= int(min_rows) and span_px is not None:
            geometry_ok = bool(float(span_px) <= float(span_max_px))
            if not geometry_ok:
                reasons.append("attached_lower_centerline_span_high")
    geometry_confidence = None
    if geometry_assessable:
        geometry_confidence = _confidence_smaller_better(
            span_px,
            full_at=float(config.get("attached_geometry_confidence_full_span_px", 25)),
            zero_at=float(config.get("attached_geometry_confidence_zero_span_px", span_max_px)),
        )
    return {
        "attached_lower_centerline_span_px": span_px,
        "attached_lower_centerline_rms_px": rms_px,
        "attached_volume_geometry_ok": geometry_ok,
        "attached_geometry_confidence": geometry_confidence,
        "attached_geometry_reasons": reasons,
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
    )
    stage4_frame = volume_mod._analyze_stage4_frame(
        stage3_frame,
        near_bottom_px=int(config["detached_near_bottom_warning_px"]),
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
    attached_near_nozzle_breakup_detected = bool(
        breakup_metrics.get("attached_near_nozzle_breakup_detected")
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
    tail_width_usable = bool(
        silhouette_qc_pass
        and nozzle_qc_pass
        and attached_width_px is not None
    )
    separated_from_nozzle_landmark = bool(
        silhouette_qc_pass
        and cutoff_y_px is not None
        and selected_component_top_y_px is not None
        and int(selected_component_top_y_px) > int(cutoff_y_px) + int(config["near_nozzle_band_top_px"])
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
    if geometry_assessable:
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
    if silhouette_qc_pass and attached_width_px is None:
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
    if attached_near_nozzle_breakup_detected:
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
        "flow_volume_complete_ok": flow_volume_complete_ok,
        "flow_volume_completeness_reasons": flow_volume_completeness_reasons,
        "flow_measurement_usable": bool(flow_measurement_usable),
        "tail_width_usable": bool(tail_width_usable),
        "separated_from_nozzle_landmark": bool(separated_from_nozzle_landmark),
        "tail_landmark_usable": bool(tail_landmark_usable),
        "landmark_reason": landmark_reason,
        "detached_near_bottom_warning": bool(detached_warning),
        "near_nozzle_detached_warning": bool(near_nozzle_detached_warning),
        "attached_near_nozzle_breakup_detected": bool(attached_near_nozzle_breakup_detected),
        "attached_band_extension_px": attached_band_extension_px,
        "attached_breakup_min_extension_px": attached_breakup_min_extension_px,
        "late_frame_warning": bool(late_frame_warning),
        "warnings": online_cal_mod._copy_warnings(warnings),
        "selected_component_top_y_px": selected_component_top_y_px,
        "cutoff_y_px": cutoff_y_px,
        "width_valid_row_count": width_metrics.get("width_valid_row_count"),
        "attached_bottom_guard_hit": bool(attached_bottom_guard_hit),
    }
    late_coverage_candidate, late_coverage_metric = online_cal_mod.is_online_stream_flow_late_coverage_candidate(
        {**summary, "delay_accepted": bool(flow_measurement_usable)}
    )
    summary["late_coverage_candidate"] = bool(late_coverage_candidate)
    summary["late_coverage_metric"] = late_coverage_metric

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
