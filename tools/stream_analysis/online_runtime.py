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
) -> dict:
    config = _resolved_analysis_config(analysis_config)
    stage3_frame = silhouette_mod._analyze_stage3_gray(
        "online_stream_runtime",
        _frame_row(
            delay_us=int(delay_us),
            emergence_time_us=int(emergence_time_us),
            capture_ref=capture_ref,
            capture_index=capture_index,
        ),
        _tracked_row(nozzle_center_px),
        silhouette_mod._coerce_gray_image(frame_image),
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
    attached_component_row = next(
        (row for row in component_rows if str(row.get("component_role") or "") == "attached_primary"),
        None,
    )
    attached_component = next(
        (
            dict(component)
            for component in list(stage3_frame.get("accepted_components") or [])
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

    warnings = []
    if not silhouette_qc_pass:
        warnings.append("silhouette_qc_failed")
    if silhouette_qc_pass and not nozzle_qc_pass:
        warnings.append("nozzle_qc_failed")
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

    if background_image is not None:
        try:
            bg_gray = silhouette_mod._coerce_gray_image(background_image)
            if bg_gray.shape[:2] != stage3_frame["gray"].shape[:2]:
                warnings.append("background_shape_mismatch")
        except Exception:
            warnings.append("background_image_unavailable")

    failure_reason = stage3_metric_row.get("failure_reason")
    if status == "rejected_nozzle_qc":
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
        "tail_width_usable": bool(tail_width_usable),
        "separated_from_nozzle_landmark": bool(separated_from_nozzle_landmark),
        "tail_landmark_usable": bool(tail_landmark_usable),
        "landmark_reason": landmark_reason,
        "detached_near_bottom_warning": bool(detached_warning),
        "near_nozzle_detached_warning": bool(near_nozzle_detached_warning),
        "late_frame_warning": bool(late_frame_warning),
        "warnings": online_cal_mod._copy_warnings(warnings),
        "selected_component_top_y_px": selected_component_top_y_px,
        "cutoff_y_px": cutoff_y_px,
        "width_valid_row_count": width_metrics.get("width_valid_row_count"),
        "attached_bottom_guard_hit": bool(attached_bottom_guard_hit),
    }

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
