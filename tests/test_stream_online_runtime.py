from __future__ import annotations

import json

import numpy as np
import pytest

from tools.stream_analysis import online_runtime as mod


NOZZLE_CENTER_PX = (110, 60)


def _blank_frame():
    return np.full((320, 220), 230, dtype=np.uint8)


def _frame_with_attached_stream(*, bottom_y: int = 170):
    frame = _blank_frame()
    frame[62:bottom_y, 96:124] = 20
    return frame


def _frame_with_stream_bounds(x0: int, x1: int, *, bottom_y: int = 170):
    frame = _blank_frame()
    frame[62:bottom_y, int(x0) : int(x1)] = 20
    return frame


def _frame_with_detached_warning():
    frame = _frame_with_attached_stream(bottom_y=170)
    frame[250:280, 100:116] = 20
    return frame


def _frame_with_near_nozzle_detached_warning():
    frame = _blank_frame()
    frame[62:108, 96:124] = 20
    frame[116:150, 100:116] = 20
    return frame


def _color_frame_with_component(
    mask: np.ndarray,
    *,
    image_height: int,
    image_width: int = 220,
    roi_x0: int = 100,
    roi_y0: int = 50,
    highlight_rows: tuple[int, int] | None = None,
):
    frame = np.full((image_height, image_width, 3), 230, dtype=np.uint8)
    height = min(int(mask.shape[0]), max(0, image_height - int(roi_y0)))
    width = min(int(mask.shape[1]), max(0, image_width - int(roi_x0)))
    view = frame[int(roi_y0) : int(roi_y0) + height, int(roi_x0) : int(roi_x0) + width]
    fg = mask[:height, :width] > 0
    view[fg] = np.array([20, 20, 20], dtype=np.uint8)
    if highlight_rows is not None:
        row_start, row_end = highlight_rows
        for y_local in range(max(0, int(row_start)), min(int(row_end), height)):
            x_indices = np.flatnonzero(mask[y_local, :width] > 0)
            if x_indices.size <= 0:
                continue
            view[y_local, int(x_indices[0])] = np.array([255, 0, 0], dtype=np.uint8)
            view[y_local, int(x_indices[-1])] = np.array([0, 0, 255], dtype=np.uint8)
    return frame


def _edge_rows_from_centerline(*, y_start: int, y_end: int, center_fn, half_width: int = 10):
    rows = []
    for y_px in range(y_start, y_end):
        center_x_px = float(center_fn(y_px))
        rows.append(
            {
                "y_px": int(y_px),
                "x_left_px": float(center_x_px - float(half_width)),
                "x_right_px": float(center_x_px + float(half_width)),
                "width_px": float(2 * half_width),
                "center_x_px": float(center_x_px),
            }
        )
    return rows


def _edge_rows_from_width_fn(*, y_start: int, y_end: int, width_fn, center_x_px: float = 110.0):
    rows = []
    for y_px in range(y_start, y_end):
        width_px = float(width_fn(y_px))
        half_width = float(width_px) / 2.0
        rows.append(
            {
                "y_px": int(y_px),
                "x_left_px": float(center_x_px - half_width),
                "x_right_px": float(center_x_px + half_width),
                "width_px": float(width_px),
                "center_x_px": float(center_x_px),
            }
        )
    return rows


def _component_from_mask(mask: np.ndarray, *, component_id: str, anchor_center_x_px: float):
    edge_rows = []
    occupied_rows = np.flatnonzero(np.any(mask > 0, axis=1))
    for y_local in occupied_rows.tolist():
        x_indices = np.flatnonzero(mask[y_local] > 0)
        edge_rows.append(
            {
                "y_px": int(50 + y_local),
                "x_left_px": float(100 + int(x_indices[0])),
                "x_right_px": float(100 + int(x_indices[-1])),
                "width_px": float(int(x_indices[-1]) - int(x_indices[0])),
                "center_x_px": float(100 + ((int(x_indices[0]) + int(x_indices[-1])) / 2.0)),
            }
        )
    return {
        "component_id": str(component_id),
        "component_role": "detached_accepted",
        "anchor_center_x_px": float(anchor_center_x_px),
        "final_mask": mask,
        "edge_rows": edge_rows,
    }


def test_analyze_online_stream_frame_returns_measurement_for_valid_attached_stream():
    frame = _frame_with_attached_stream(bottom_y=170)
    result = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "accepted"
    assert summary["measurement_qc_pass"] is True
    assert summary["silhouette_status"] == "ok"
    assert summary["attached_width_px"] is not None
    assert summary["visible_volume_nl"] is not None
    assert summary["attached_bottom_clearance_px"] > 96
    assert summary["flow_volume_geometry_ok"] is True
    assert summary["flow_measurement_usable"] is True
    assert summary["flow_geometry_confidence"] is not None
    assert summary["flow_optical_confidence"] is not None
    assert summary["flow_point_confidence"] is not None
    assert summary["lower_edge_jitter_px"] is not None
    assert summary["boundary_chroma_aberration_score"] == 0.0
    assert result["overlay"] is not None
    assert result["overlay"].shape == frame.shape + (3,)
    assert np.any(result["overlay"][80:170, 96:124] != np.stack([frame[80:170, 96:124]] * 3, axis=-1))


def test_analyze_online_stream_frame_expands_left_when_contour_nears_corridor_edge():
    frame = _frame_with_stream_bounds(50, 124, bottom_y=170)
    disabled = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config={"adaptive_roi_expansion_enabled": False},
        _adaptive_retry=False,
    )
    expanded = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
        _adaptive_retry=False,
    )

    disabled_summary = disabled["summary"]
    expanded_summary = expanded["summary"]
    assert disabled_summary["adaptive_roi_expansion_triggered"] is False
    assert expanded_summary["adaptive_roi_expansion_triggered"] is True
    assert expanded_summary["adaptive_roi_expansion_sides"] == ["left"]
    assert expanded_summary["adaptive_roi_left_expansion_px"] > 0
    assert expanded_summary["adaptive_roi_right_expansion_px"] == 0
    assert expanded_summary["visible_volume_nl"] > disabled_summary["visible_volume_nl"]
    assert expanded_summary["selected_component_corridor_left_clearance_px"] > 8
    assert expanded_summary["base_corridor_x0"] > expanded_summary["base_roi_x0"]


def test_analyze_online_stream_frame_expands_right_when_contour_nears_corridor_edge():
    frame = _frame_with_stream_bounds(96, 170, bottom_y=170)
    result = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
        _adaptive_retry=False,
    )

    summary = result["summary"]
    assert summary["adaptive_roi_expansion_triggered"] is True
    assert summary["adaptive_roi_expansion_sides"] == ["right"]
    assert summary["adaptive_roi_left_expansion_px"] == 0
    assert summary["adaptive_roi_right_expansion_px"] > 0
    assert summary["selected_component_corridor_right_clearance_px"] > 8


def test_analyze_online_stream_frame_does_not_expand_centered_stream():
    frame = _frame_with_attached_stream(bottom_y=170)
    result = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
        _adaptive_retry=False,
    )

    summary = result["summary"]
    assert summary["adaptive_roi_expansion_triggered"] is False
    assert summary["adaptive_roi_expansion_sides"] == []
    assert summary["adaptive_roi_left_expansion_px"] == 0
    assert summary["adaptive_roi_right_expansion_px"] == 0
    assert summary["adaptive_roi_stop_reason"] == "clearance_ok"
    assert summary["base_roi_x0"] == 72
    assert summary["base_roi_x1"] == 149
    assert summary["base_corridor_x0"] == 83
    assert summary["base_corridor_x1"] == 137


def test_analyze_online_stream_frame_stops_expansion_at_image_edge():
    frame = _frame_with_stream_bounds(0, 40, bottom_y=170)
    result = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=(30, 60),
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
        _adaptive_retry=False,
    )

    summary = result["summary"]
    assert summary["adaptive_roi_expansion_triggered"] is True
    assert summary["adaptive_roi_expansion_sides"] == ["left"]
    assert summary["adaptive_roi_stop_reason"] == "image_edge_reached"
    assert summary["visible_volume_nl"] is not None


def test_online_stream_overlay_preserves_full_frame_and_distinguishes_component_roles():
    frame = _frame_with_detached_warning()
    result = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    overlay = result["overlay"]
    assert overlay is not None
    assert overlay.shape == frame.shape + (3,)
    assert np.array_equal(overlay[305, 200], np.array([230, 230, 230], dtype=np.uint8))

    attached_pixel = overlay[120, 110]
    detached_pixel = overlay[260, 108]
    assert np.any(attached_pixel != np.array([20, 20, 20], dtype=np.uint8))
    assert np.any(detached_pixel != np.array([20, 20, 20], dtype=np.uint8))
    assert not np.array_equal(attached_pixel, detached_pixel)


def test_analyze_online_stream_frame_rejects_blank_frame_without_geometry():
    result = mod.analyze_online_stream_frame(
        frame_image=_blank_frame(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["measurement_qc_pass"] is False
    assert summary["silhouette_status"] != "ok"
    assert summary["visible_volume_nl"] is None


def test_analyze_online_stream_frame_rejects_when_too_few_width_rows_exist():
    frame = _blank_frame()
    frame[62:88, 96:124] = 20

    result = mod.analyze_online_stream_frame(
        frame_image=frame,
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["measurement_qc_pass"] is False
    assert summary["status"] == "rejected_width_qc"
    assert summary["attached_width_px"] is None


def test_analyze_online_stream_frame_marks_attached_bottom_guard_hit():
    result = mod.analyze_online_stream_frame(
        frame_image=_frame_with_attached_stream(bottom_y=260),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["measurement_qc_pass"] is False
    assert summary["status"] == "rejected_bottom_guard"
    assert summary["attached_bottom_guard_hit"] is True
    assert summary["late_frame_warning"] is True
    assert summary["attached_bottom_clearance_px"] <= 96


def test_analyze_online_stream_frame_preserves_tail_width_even_when_flow_bottom_guard_rejects():
    result = mod.analyze_online_stream_frame(
        frame_image=_frame_with_attached_stream(bottom_y=260),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "rejected_bottom_guard"
    assert summary["measurement_qc_pass"] is False
    assert summary["nozzle_qc_pass"] is True
    assert summary["attached_width_px"] is not None


def test_analyze_online_stream_frame_warns_for_detached_near_bottom_without_rejecting():
    result = mod.analyze_online_stream_frame(
        frame_image=_frame_with_detached_warning(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "accepted"
    assert summary["measurement_qc_pass"] is True
    assert summary["detached_near_bottom_warning"] is True
    assert summary["late_frame_warning"] is True
    assert summary["flow_volume_geometry_ok"] is True
    assert "detached_near_bottom_warning" in summary["warnings"]


def test_online_stream_runtime_marks_late_coverage_candidate_when_detached_fluid_reaches_lower_fov():
    result = mod.analyze_online_stream_frame(
        frame_image=_frame_with_detached_warning(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=5500,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["min_accepted_fluid_distance_from_bottom_px"] is not None
    assert "late_coverage_candidate" in summary
    if summary["late_coverage_candidate"]:
        assert summary["late_coverage_metric"] in {"delay_threshold", "visible_fluid_bottom_clearance"}
    else:
        assert summary["flow_point_confidence"] is not None
        assert summary["flow_point_confidence"] < 0.70


def test_analyze_online_stream_frame_marks_material_plausible_unaccepted_volume_as_incomplete(monkeypatch):
    attached_mask = np.zeros((220, 80), dtype=np.uint8)
    attached_mask[12:128, 30:50] = 255
    attached_component = _component_from_mask(
        attached_mask,
        component_id="attached_primary",
        anchor_center_x_px=110.0,
    )
    attached_component["component_role"] = "attached_primary"
    attached_component["component_rank"] = 0

    stage3_frame = {
        "metric_row": {
            "silhouette_status": "ok",
            "tracked_nozzle_x_px": 110.0,
            "tracked_nozzle_y_px": 60.0,
            "tracked_confidence": 1.0,
            "raw_mode": "segment",
            "final_mode": "segment",
            "segment_id": 1,
            "shift_event_before": False,
            "cutoff_y_px": 62,
            "selected_component_top_y_px": 62,
            "selected_component_bottom_y_px": 177,
            "roi_y1": 320,
            "accepted_component_count": 1,
            "accepted_detached_component_count": 0,
            "plausible_unaccepted_component_count": 1,
        },
        "component_rows": [
            {
                "component_id": "attached_primary",
                "component_role": "attached_primary",
                "component_rank": 0,
                "top_y_px": 62,
                "bottom_y_px": 177,
                "last_valid_y_px": 177,
            },
            {
                "component_id": "plausible_detached_01",
                "component_role": "detached_plausible_unaccepted",
                "component_rank": 1,
                "top_y_px": 190,
                "bottom_y_px": 225,
                "last_valid_y_px": 225,
            },
        ],
        "accepted_components": [attached_component],
        "roi": {"x0": 70, "y0": 50, "x1": 150, "y1": 320, "width": 80, "height": 270},
    }
    stage4_frame = {
        "frame_metric_row": {
            "total_visible_volume_nl": 18.0,
            "detached_visible_volume_nl": 0.0,
            "plausible_unaccepted_visible_volume_nl": 1.2,
            "min_accepted_fluid_distance_from_bottom_px": 82,
        },
        "component_volume_rows": [],
    }

    monkeypatch.setattr(mod.silhouette_mod, "_analyze_stage3_gray", lambda *args, **kwargs: stage3_frame)
    monkeypatch.setattr(mod.volume_mod, "_analyze_stage4_frame", lambda *args, **kwargs: stage4_frame)

    result = mod.analyze_online_stream_frame(
        frame_image=_blank_frame(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "accepted"
    assert summary["measurement_qc_pass"] is True
    assert summary["flow_volume_complete_ok"] is False
    assert summary["flow_volume_completeness_reasons"] == ["material_plausible_unaccepted_detached"]
    assert summary["plausible_unaccepted_component_count"] == 1
    assert summary["plausible_unaccepted_visible_volume_nl"] == pytest.approx(1.2)
    assert summary["flow_measurement_usable"] is False
    assert "flow_volume_incomplete" in summary["warnings"]


def test_analyze_online_stream_frame_marks_near_nozzle_detached_warning():
    result = mod.analyze_online_stream_frame(
        frame_image=_frame_with_near_nozzle_detached_warning(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "accepted"
    assert summary["measurement_qc_pass"] is True
    assert summary["near_nozzle_detached_warning"] is True
    assert summary["late_frame_warning"] is False
    assert "near_nozzle_detached_warning" in summary["warnings"]


def test_attached_near_nozzle_breakup_detects_short_stub_only_when_continuity_is_missing():
    config = mod._resolved_analysis_config(None)

    detected = mod._attached_near_nozzle_breakup(
        {
            "accepted_detached_component_count": 2,
            "roi_height": 270,
        },
        {"last_valid_y_px": 140},
        {"band_y1_px": 124},
        config=config,
    )
    assert detected["attached_near_nozzle_breakup_detected"] is True
    assert detected["attached_band_extension_px"] == 17
    assert detected["attached_breakup_min_extension_px"] == 40

    preserved = mod._attached_near_nozzle_breakup(
        {
            "accepted_detached_component_count": 2,
            "roi_height": 270,
        },
        {"last_valid_y_px": 170},
        {"band_y1_px": 124},
        config=config,
    )
    assert preserved["attached_near_nozzle_breakup_detected"] is False
    assert preserved["attached_band_extension_px"] == 47


def test_band_width_metrics_uses_lower_consistent_window_for_spread_heavy_root_band():
    config = mod._resolved_analysis_config(None)
    edge_rows = []
    edge_rows.extend(_edge_rows_from_width_fn(y_start=84, y_end=104, width_fn=lambda y: 118.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=104, y_end=124, width_fn=lambda y: 78.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=124, y_end=164, width_fn=lambda y: 88.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=164, y_end=184, width_fn=lambda y: 42.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=184, y_end=224, width_fn=lambda y: 40.0))

    metrics = mod._band_width_metrics(
        {"tracked_nozzle_y_px": 60.0},
        edge_rows,
        near_nozzle_band_top_px=int(config["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(config["near_nozzle_band_height_px"]),
        min_band_valid_rows=int(config["min_band_valid_rows"]),
    )

    assert metrics["attached_width_mode"] == "lower_consistent_window"
    assert metrics["spread_fallback_triggered"] is True
    assert metrics["attached_width_px"] == pytest.approx(41.0)
    assert metrics["root_band_width_px"] == pytest.approx(98.0)
    assert metrics["root_band_width_iqr_px"] == pytest.approx(40.0)
    assert metrics["root_band_half_delta_px"] == pytest.approx(40.0)
    assert metrics["selected_band_y0_px"] == 164
    assert metrics["selected_band_y1_px"] == 204
    assert metrics["selected_band_valid_row_count"] == 40
    assert metrics["candidate_window_count"] >= 4


def test_band_width_metrics_keeps_root_band_for_normal_stream():
    config = mod._resolved_analysis_config(None)
    edge_rows = _edge_rows_from_width_fn(
        y_start=84,
        y_end=224,
        width_fn=lambda y: 66.0,
    )

    metrics = mod._band_width_metrics(
        {"tracked_nozzle_y_px": 60.0},
        edge_rows,
        near_nozzle_band_top_px=int(config["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(config["near_nozzle_band_height_px"]),
        min_band_valid_rows=int(config["min_band_valid_rows"]),
    )

    assert metrics["attached_width_mode"] == "root_band"
    assert metrics["spread_fallback_triggered"] is False
    assert metrics["attached_width_px"] == pytest.approx(66.0)
    assert metrics["selected_band_y0_px"] == 84
    assert metrics["selected_band_y1_px"] == 124
    assert metrics["candidate_window_count"] == 0


def test_band_width_metrics_keeps_root_band_for_normal_taper():
    config = mod._resolved_analysis_config(None)
    edge_rows = []
    edge_rows.extend(_edge_rows_from_width_fn(y_start=84, y_end=104, width_fn=lambda y: 82.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=104, y_end=124, width_fn=lambda y: 72.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=124, y_end=224, width_fn=lambda y: 58.0))

    metrics = mod._band_width_metrics(
        {"tracked_nozzle_y_px": 60.0},
        edge_rows,
        near_nozzle_band_top_px=int(config["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(config["near_nozzle_band_height_px"]),
        min_band_valid_rows=int(config["min_band_valid_rows"]),
    )

    assert metrics["attached_width_mode"] == "root_band"
    assert metrics["spread_fallback_triggered"] is False
    assert metrics["attached_width_px"] == pytest.approx(77.0)
    assert metrics["root_band_width_iqr_px"] == pytest.approx(10.0)
    assert metrics["root_band_half_delta_px"] == pytest.approx(10.0)


def test_band_width_metrics_keeps_root_band_when_no_trustworthy_lower_candidate_exists():
    config = mod._resolved_analysis_config(None)
    edge_rows = []
    edge_rows.extend(_edge_rows_from_width_fn(y_start=84, y_end=104, width_fn=lambda y: 118.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=104, y_end=124, width_fn=lambda y: 78.0))
    edge_rows.extend(_edge_rows_from_width_fn(y_start=124, y_end=164, width_fn=lambda y: 88.0))
    edge_rows.extend(
        _edge_rows_from_width_fn(
            y_start=164,
            y_end=204,
            width_fn=lambda y: 10.0 if (int(y) % 2 == 0) else 70.0,
        )
    )
    edge_rows.extend(_edge_rows_from_width_fn(y_start=204, y_end=244, width_fn=lambda y: 38.0))

    metrics = mod._band_width_metrics(
        {"tracked_nozzle_y_px": 60.0},
        edge_rows,
        near_nozzle_band_top_px=int(config["near_nozzle_band_top_px"]),
        near_nozzle_band_height_px=int(config["near_nozzle_band_height_px"]),
        min_band_valid_rows=int(config["min_band_valid_rows"]),
    )

    assert metrics["attached_width_mode"] == "root_band"
    assert metrics["spread_fallback_triggered"] is False
    assert metrics["attached_width_px"] == pytest.approx(98.0)
    assert metrics["candidate_window_count"] >= 4


def test_analyze_online_stream_frame_rejects_short_attached_stub_with_multiple_detached_components(monkeypatch):
    attached_mask = np.zeros((220, 80), dtype=np.uint8)
    attached_mask[12:91, 30:50] = 255
    attached_component = _component_from_mask(
        attached_mask,
        component_id="attached_primary",
        anchor_center_x_px=110.0,
    )
    attached_component["component_role"] = "attached_primary"
    attached_component["component_rank"] = 0

    stage3_frame = {
        "metric_row": {
            "silhouette_status": "ok",
            "tracked_nozzle_x_px": 110.0,
            "tracked_nozzle_y_px": 60.0,
            "tracked_confidence": 1.0,
            "raw_mode": "segment",
            "final_mode": "segment",
            "segment_id": 1,
            "shift_event_before": False,
            "cutoff_y_px": 62,
            "selected_component_top_y_px": 62,
            "selected_component_bottom_y_px": 140,
            "roi_y0": 50,
            "roi_y1": 320,
            "roi_height": 270,
            "accepted_component_count": 3,
            "accepted_detached_component_count": 2,
            "plausible_unaccepted_component_count": 0,
        },
        "component_rows": [
            {
                "component_id": "attached_primary",
                "component_role": "attached_primary",
                "component_rank": 0,
                "top_y_px": 62,
                "bottom_y_px": 140,
                "last_valid_y_px": 140,
            },
            {
                "component_id": "detached_01",
                "component_role": "detached_accepted",
                "component_rank": 1,
                "top_y_px": 176,
                "bottom_y_px": 196,
                "last_valid_y_px": 196,
            },
            {
                "component_id": "detached_02",
                "component_role": "detached_accepted",
                "component_rank": 2,
                "top_y_px": 224,
                "bottom_y_px": 248,
                "last_valid_y_px": 248,
            },
        ],
        "accepted_components": [attached_component],
        "roi": {"x0": 70, "y0": 50, "x1": 150, "y1": 320, "width": 80, "height": 270},
    }
    stage4_frame = {
        "frame_metric_row": {
            "total_visible_volume_nl": 18.0,
            "detached_visible_volume_nl": 0.0,
            "plausible_unaccepted_visible_volume_nl": 0.0,
            "min_accepted_fluid_distance_from_bottom_px": 72,
        },
        "component_volume_rows": [],
    }

    monkeypatch.setattr(mod.silhouette_mod, "_analyze_stage3_gray", lambda *args, **kwargs: stage3_frame)
    monkeypatch.setattr(mod.volume_mod, "_analyze_stage4_frame", lambda *args, **kwargs: stage4_frame)

    result = mod.analyze_online_stream_frame(
        frame_image=_blank_frame(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "rejected_width_qc"
    assert summary["measurement_qc_pass"] is False
    assert summary["attached_width_px"] is None
    assert summary["attached_near_nozzle_breakup_detected"] is True
    assert summary["attached_band_extension_px"] == 17
    assert summary["attached_breakup_min_extension_px"] == 40
    assert "attached_near_nozzle_breakup" in summary["warnings"]
    assert "attached_width_unavailable" in summary["warnings"]


def test_analyze_online_stream_frame_marks_single_detached_continuation_below_short_stub(monkeypatch):
    attached_mask = np.zeros((220, 80), dtype=np.uint8)
    attached_mask[12:91, 30:50] = 255
    attached_component = _component_from_mask(
        attached_mask,
        component_id="attached_primary",
        anchor_center_x_px=110.0,
    )
    attached_component["component_role"] = "attached_primary"
    attached_component["component_rank"] = 0

    detached_mask = np.zeros((220, 80), dtype=np.uint8)
    detached_mask[126:210, 30:50] = 255
    detached_component = _component_from_mask(
        detached_mask,
        component_id="detached_01",
        anchor_center_x_px=110.0,
    )
    detached_component["component_role"] = "detached_accepted"
    detached_component["component_rank"] = 1

    stage3_frame = {
        "metric_row": {
            "silhouette_status": "ok",
            "tracked_nozzle_x_px": 110.0,
            "tracked_nozzle_y_px": 60.0,
            "tracked_confidence": 1.0,
            "raw_mode": "segment",
            "final_mode": "segment",
            "segment_id": 1,
            "shift_event_before": False,
            "cutoff_y_px": 62,
            "selected_component_top_y_px": 62,
            "selected_component_bottom_y_px": 140,
            "roi_y0": 50,
            "roi_y1": 320,
            "roi_height": 270,
            "accepted_component_count": 2,
            "accepted_detached_component_count": 1,
            "plausible_unaccepted_component_count": 0,
        },
        "component_rows": [
            {
                "component_id": "attached_primary",
                "component_role": "attached_primary",
                "component_rank": 0,
                "top_y_px": 62,
                "bottom_y_px": 140,
                "last_valid_y_px": 140,
            },
            {
                "component_id": "detached_01",
                "component_role": "detached_accepted",
                "component_rank": 1,
                "top_y_px": 176,
                "bottom_y_px": 259,
                "last_valid_y_px": 259,
            },
        ],
        "accepted_components": [attached_component, detached_component],
        "roi": {"x0": 70, "y0": 50, "x1": 150, "y1": 320, "width": 80, "height": 270},
    }
    stage4_frame = {
        "frame_metric_row": {
            "total_visible_volume_nl": 18.0,
            "detached_visible_volume_nl": 4.0,
            "plausible_unaccepted_visible_volume_nl": 0.0,
            "min_accepted_fluid_distance_from_bottom_px": 60,
        },
        "component_volume_rows": [],
    }

    monkeypatch.setattr(mod.silhouette_mod, "_analyze_stage3_gray", lambda *args, **kwargs: stage3_frame)
    monkeypatch.setattr(mod.volume_mod, "_analyze_stage4_frame", lambda *args, **kwargs: stage4_frame)

    result = mod.analyze_online_stream_frame(
        frame_image=_blank_frame(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "rejected_width_qc"
    assert summary["attached_width_px"] is None
    assert summary["measurement_qc_pass"] is False
    assert summary["tail_width_usable"] is False
    assert summary["tail_landmark_usable"] is True
    assert summary["attached_near_nozzle_breakup_detected"] is True
    assert summary["residue_stub_with_detached_continuation"] is True
    assert summary["separated_from_nozzle_landmark"] is True
    assert summary["separation_mode"] == "detached_continuation_below_stub"
    assert summary["effective_stream_owner"] == "detached_continuation"
    assert summary["detached_continuation_component_id"] == "detached_01"
    assert summary["detached_continuation_gap_px"] == 35
    assert summary["detached_continuation_height_px"] == 84
    assert summary["detached_continuation_row_count"] >= 40
    assert "residue_stub_with_detached_continuation" in summary["warnings"]
    assert "attached_width_unavailable" not in summary["warnings"]


def test_analyze_online_stream_frame_preserves_attached_owner_when_stub_is_not_short(monkeypatch):
    attached_mask = np.zeros((220, 80), dtype=np.uint8)
    attached_mask[12:170, 30:50] = 255
    attached_component = _component_from_mask(
        attached_mask,
        component_id="attached_primary",
        anchor_center_x_px=110.0,
    )
    attached_component["component_role"] = "attached_primary"
    attached_component["component_rank"] = 0

    detached_mask = np.zeros((220, 80), dtype=np.uint8)
    detached_mask[176:210, 30:50] = 255
    detached_component = _component_from_mask(
        detached_mask,
        component_id="detached_01",
        anchor_center_x_px=110.0,
    )
    detached_component["component_role"] = "detached_accepted"
    detached_component["component_rank"] = 1

    stage3_frame = {
        "metric_row": {
            "silhouette_status": "ok",
            "tracked_nozzle_x_px": 110.0,
            "tracked_nozzle_y_px": 60.0,
            "tracked_confidence": 1.0,
            "raw_mode": "segment",
            "final_mode": "segment",
            "segment_id": 1,
            "shift_event_before": False,
            "cutoff_y_px": 62,
            "selected_component_top_y_px": 62,
            "selected_component_bottom_y_px": 219,
            "roi_y0": 50,
            "roi_y1": 320,
            "roi_height": 270,
            "accepted_component_count": 2,
            "accepted_detached_component_count": 1,
            "plausible_unaccepted_component_count": 0,
        },
        "component_rows": [
            {
                "component_id": "attached_primary",
                "component_role": "attached_primary",
                "component_rank": 0,
                "top_y_px": 62,
                "bottom_y_px": 219,
                "last_valid_y_px": 219,
            },
            {
                "component_id": "detached_01",
                "component_role": "detached_accepted",
                "component_rank": 1,
                "top_y_px": 226,
                "bottom_y_px": 259,
                "last_valid_y_px": 259,
            },
        ],
        "accepted_components": [attached_component, detached_component],
        "roi": {"x0": 70, "y0": 50, "x1": 150, "y1": 320, "width": 80, "height": 270},
    }
    stage4_frame = {
        "frame_metric_row": {
            "total_visible_volume_nl": 18.0,
            "detached_visible_volume_nl": 1.2,
            "plausible_unaccepted_visible_volume_nl": 0.0,
            "min_accepted_fluid_distance_from_bottom_px": 60,
        },
        "component_volume_rows": [],
    }

    monkeypatch.setattr(mod.silhouette_mod, "_analyze_stage3_gray", lambda *args, **kwargs: stage3_frame)
    monkeypatch.setattr(mod.volume_mod, "_analyze_stage4_frame", lambda *args, **kwargs: stage4_frame)

    result = mod.analyze_online_stream_frame(
        frame_image=_blank_frame(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "accepted"
    assert summary["measurement_qc_pass"] is True
    assert summary["attached_width_px"] is not None
    assert summary["residue_stub_with_detached_continuation"] is False
    assert summary["separated_from_nozzle_landmark"] is False
    assert summary["effective_stream_owner"] == "attached_primary"


def test_analyze_online_stream_frame_rejects_small_detached_body_as_continuation(monkeypatch):
    attached_mask = np.zeros((220, 80), dtype=np.uint8)
    attached_mask[12:91, 30:50] = 255
    attached_component = _component_from_mask(
        attached_mask,
        component_id="attached_primary",
        anchor_center_x_px=110.0,
    )
    attached_component["component_role"] = "attached_primary"
    attached_component["component_rank"] = 0

    detached_mask = np.zeros((220, 80), dtype=np.uint8)
    detached_mask[126:145, 30:50] = 255
    detached_component = _component_from_mask(
        detached_mask,
        component_id="detached_01",
        anchor_center_x_px=110.0,
    )
    detached_component["component_role"] = "detached_accepted"
    detached_component["component_rank"] = 1

    stage3_frame = {
        "metric_row": {
            "silhouette_status": "ok",
            "tracked_nozzle_x_px": 110.0,
            "tracked_nozzle_y_px": 60.0,
            "tracked_confidence": 1.0,
            "raw_mode": "segment",
            "final_mode": "segment",
            "segment_id": 1,
            "shift_event_before": False,
            "cutoff_y_px": 62,
            "selected_component_top_y_px": 62,
            "selected_component_bottom_y_px": 140,
            "roi_y0": 50,
            "roi_y1": 320,
            "roi_height": 270,
            "accepted_component_count": 2,
            "accepted_detached_component_count": 1,
            "plausible_unaccepted_component_count": 0,
        },
        "component_rows": [
            {
                "component_id": "attached_primary",
                "component_role": "attached_primary",
                "component_rank": 0,
                "top_y_px": 62,
                "bottom_y_px": 140,
                "last_valid_y_px": 140,
            },
            {
                "component_id": "detached_01",
                "component_role": "detached_accepted",
                "component_rank": 1,
                "top_y_px": 176,
                "bottom_y_px": 194,
                "last_valid_y_px": 194,
            },
        ],
        "accepted_components": [attached_component, detached_component],
        "roi": {"x0": 70, "y0": 50, "x1": 150, "y1": 320, "width": 80, "height": 270},
    }
    stage4_frame = {
        "frame_metric_row": {
            "total_visible_volume_nl": 18.0,
            "detached_visible_volume_nl": 0.3,
            "plausible_unaccepted_visible_volume_nl": 0.0,
            "min_accepted_fluid_distance_from_bottom_px": 60,
        },
        "component_volume_rows": [],
    }

    monkeypatch.setattr(mod.silhouette_mod, "_analyze_stage3_gray", lambda *args, **kwargs: stage3_frame)
    monkeypatch.setattr(mod.volume_mod, "_analyze_stage4_frame", lambda *args, **kwargs: stage4_frame)

    result = mod.analyze_online_stream_frame(
        frame_image=_blank_frame(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "accepted"
    assert summary["measurement_qc_pass"] is True
    assert summary["attached_width_px"] is not None
    assert summary["residue_stub_with_detached_continuation"] is False
    assert summary["detached_continuation_row_count"] < 40
    assert summary["separated_from_nozzle_landmark"] is False


def test_analyze_online_stream_frame_marks_direct_departure_as_separation(monkeypatch):
    attached_mask = np.zeros((220, 80), dtype=np.uint8)
    attached_mask[70:110, 30:50] = 255
    attached_component = _component_from_mask(
        attached_mask,
        component_id="attached_primary",
        anchor_center_x_px=110.0,
    )
    attached_component["component_role"] = "attached_primary"
    attached_component["component_rank"] = 0

    stage3_frame = {
        "metric_row": {
            "silhouette_status": "ok",
            "tracked_nozzle_x_px": 110.0,
            "tracked_nozzle_y_px": 60.0,
            "tracked_confidence": 1.0,
            "raw_mode": "segment",
            "final_mode": "segment",
            "segment_id": 1,
            "shift_event_before": False,
            "cutoff_y_px": 62,
            "selected_component_top_y_px": 120,
            "selected_component_bottom_y_px": 159,
            "roi_y0": 50,
            "roi_y1": 320,
            "roi_height": 270,
            "accepted_component_count": 1,
            "accepted_detached_component_count": 0,
            "plausible_unaccepted_component_count": 0,
        },
        "component_rows": [
            {
                "component_id": "attached_primary",
                "component_role": "attached_primary",
                "component_rank": 0,
                "top_y_px": 120,
                "bottom_y_px": 159,
                "last_valid_y_px": 159,
            },
        ],
        "accepted_components": [attached_component],
        "roi": {"x0": 70, "y0": 50, "x1": 150, "y1": 320, "width": 80, "height": 270},
    }
    stage4_frame = {
        "frame_metric_row": {
            "total_visible_volume_nl": 6.0,
            "detached_visible_volume_nl": 0.0,
            "plausible_unaccepted_visible_volume_nl": 0.0,
            "min_accepted_fluid_distance_from_bottom_px": 120,
        },
        "component_volume_rows": [],
    }

    monkeypatch.setattr(mod.silhouette_mod, "_analyze_stage3_gray", lambda *args, **kwargs: stage3_frame)
    monkeypatch.setattr(mod.volume_mod, "_analyze_stage4_frame", lambda *args, **kwargs: stage4_frame)

    result = mod.analyze_online_stream_frame(
        frame_image=_blank_frame(),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4250,
        emergence_time_us=3200,
        analysis_config=None,
    )

    summary = result["summary"]
    assert summary["status"] == "rejected_nozzle_qc"
    assert summary["measurement_qc_pass"] is False
    assert summary["tail_landmark_usable"] is True
    assert summary["separated_from_nozzle_landmark"] is True
    assert summary["separation_mode"] == "selected_component_departed"
    assert summary["effective_stream_owner"] == "attached_primary"
    assert "attached_width_unavailable" not in summary["warnings"]


def test_attached_geometry_summary_passes_straight_but_angled_stream():
    edge_rows = _edge_rows_from_centerline(
        y_start=60,
        y_end=180,
        center_fn=lambda y_px: 100.0 + (0.20 * float(y_px - 60)),
    )

    geometry = mod._attached_geometry_summary(
        edge_rows,
        lower_row_fraction=0.35,
        min_rows=12,
        span_max_px=50,
        geometry_assessable=True,
    )

    assert geometry["attached_volume_geometry_ok"] is True
    assert geometry["attached_lower_centerline_span_px"] < 1.0


def test_attached_geometry_summary_fails_connected_curl():
    edge_rows = _edge_rows_from_centerline(
        y_start=60,
        y_end=180,
        center_fn=lambda y_px: (
            100.0
            + (0.15 * float(y_px - 60))
            + (
                0.0
                if y_px < 125
                else (55.0 if y_px < 150 else -55.0)
            )
        ),
    )

    geometry = mod._attached_geometry_summary(
        edge_rows,
        lower_row_fraction=0.35,
        min_rows=12,
        span_max_px=50,
        geometry_assessable=True,
    )

    assert geometry["attached_volume_geometry_ok"] is False
    assert geometry["attached_lower_centerline_span_px"] > 50.0


def test_detached_geometry_passes_compact_symmetric_body_with_moderate_axis_offset():
    mask = np.zeros((50, 60), dtype=np.uint8)
    mask[10:35, 22:38] = 1
    component = _component_from_mask(mask, component_id="det_01", anchor_center_x_px=130.0)

    detail = mod._detached_component_geometry_details(
        detached_component=component,
        component_volume_nl=1.2,
        detached_visible_volume_nl=1.2,
        roi={"x0": 100, "y0": 50},
        tracked_nozzle_x_px=145.0,
        config=mod._resolved_analysis_config(None),
    )

    assert detail["geometry_ok"] is True
    assert detail["axis_symmetry_score"] >= 0.80
    assert detail["local_centerline_span_px"] <= 20.0


def test_detached_geometry_fails_hooked_asymmetric_body():
    mask = np.zeros((50, 60), dtype=np.uint8)
    mask[10:35, 22:38] = 1
    mask[28:40, 38:52] = 1
    component = _component_from_mask(mask, component_id="det_hook", anchor_center_x_px=130.0)

    detail = mod._detached_component_geometry_details(
        detached_component=component,
        component_volume_nl=1.2,
        detached_visible_volume_nl=1.2,
        roi={"x0": 100, "y0": 50},
        tracked_nozzle_x_px=130.0,
        config=mod._resolved_analysis_config(None),
    )

    assert detail["geometry_ok"] is False
    assert "detached_axis_symmetry_low" in detail["geometry_reasons"]


def test_detached_geometry_large_axis_offset_warns_but_does_not_fail_when_shape_is_good():
    mask = np.zeros((50, 60), dtype=np.uint8)
    mask[10:35, 22:38] = 1
    component = _component_from_mask(mask, component_id="det_far", anchor_center_x_px=170.0)

    detail = mod._detached_component_geometry_details(
        detached_component=component,
        component_volume_nl=1.2,
        detached_visible_volume_nl=1.2,
        roi={"x0": 100, "y0": 50},
        tracked_nozzle_x_px=130.0,
        config=mod._resolved_analysis_config(None),
    )

    assert detail["geometry_ok"] is True
    assert detail["axis_offset_px"] > 25.0
    assert detail["geometry_reasons"] == []


def test_detached_geometry_ignores_immaterial_specks():
    mask = np.zeros((30, 30), dtype=np.uint8)
    mask[10:14, 12:16] = 1
    component = _component_from_mask(mask, component_id="det_speck", anchor_center_x_px=120.0)

    detail = mod._detached_component_geometry_details(
        detached_component=component,
        component_volume_nl=0.1,
        detached_visible_volume_nl=1.0,
        roi={"x0": 100, "y0": 50},
        tracked_nozzle_x_px=120.0,
        config=mod._resolved_analysis_config(None),
    )

    assert detail["geometry_ok"] is True
    assert detail["axis_symmetry_score"] is None


def test_attached_optical_summary_is_inactive_far_from_lower_fov_even_with_poor_raw_metrics():
    mask = np.zeros((320, 60), dtype=np.uint8)
    mask[10:260, 22:38] = 1
    component = _component_from_mask(mask, component_id="attached_01", anchor_center_x_px=130.0)
    frame = _color_frame_with_component(
        mask,
        image_height=1200,
        highlight_rows=(190, 260),
    )

    optical = mod._attached_optical_summary(
        frame_image=frame,
        attached_edge_rows=list(component["edge_rows"]),
        attached_component=component,
        roi={"x0": 100, "y0": 50, "x1": 160, "y1": 1170},
        visible_fluid_clearance_px=700.0,
        lower_row_fraction=0.25,
        config=mod._resolved_analysis_config(None),
        geometry_assessable=True,
        frame_color_order="bgr",
    )

    assert optical["flow_optical_confidence_active"] is False
    assert optical["optical_activation_clearance_px"] == 400.0
    assert optical["boundary_chroma_aberration_score"] is not None
    assert optical["boundary_chroma_aberration_score"] > 12.0
    assert optical["flow_optical_confidence"] == 1.0


def test_attached_optical_summary_lowers_confidence_when_active_near_lower_fov():
    mask = np.zeros((1040, 60), dtype=np.uint8)
    mask[10:980, 22:38] = 1
    component = _component_from_mask(mask, component_id="attached_02", anchor_center_x_px=130.0)
    frame = _color_frame_with_component(
        mask,
        image_height=1200,
        highlight_rows=(850, 980),
    )

    optical = mod._attached_optical_summary(
        frame_image=frame,
        attached_edge_rows=list(component["edge_rows"]),
        attached_component=component,
        roi={"x0": 100, "y0": 50, "x1": 160, "y1": 1170},
        visible_fluid_clearance_px=170.0,
        lower_row_fraction=0.25,
        config=mod._resolved_analysis_config(None),
        geometry_assessable=True,
        frame_color_order="bgr",
    )

    assert optical["flow_optical_confidence_active"] is True
    assert optical["flow_optical_confidence"] is not None
    assert optical["flow_optical_confidence"] < 1.0


def test_online_runtime_summary_is_json_serializable():
    result = mod.analyze_online_stream_frame(
        frame_image=_frame_with_attached_stream(bottom_y=170),
        background_image=_blank_frame(),
        nozzle_center_px=NOZZLE_CENTER_PX,
        delay_us=4050,
        emergence_time_us=3200,
        analysis_config=None,
    )

    encoded = json.dumps(result["summary"])

    assert isinstance(encoded, str)
    assert "measurement_qc_pass" in encoded
