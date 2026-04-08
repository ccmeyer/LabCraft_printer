from __future__ import annotations

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

    overlay = None
    try:
        sample_input = dict(stage3_frame)
        sample_input["metric_row"] = dict(stage4_frame.get("labeled_stage3_row") or stage3_metric_row)
        overlay = volume_mod._build_sample_panel(
            stage3_frame["gray"],
            sample_input=sample_input,
            frame_metric_row=frame_metric_row,
            component_volume_rows=list(stage4_frame.get("component_volume_rows") or []),
            fov_report=dict(stage4_frame.get("fov_report") or {}),
        )
    except Exception:
        overlay = None

    return {
        "summary": {
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
        },
        "overlay": overlay,
    }
