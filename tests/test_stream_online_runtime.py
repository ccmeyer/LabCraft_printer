from __future__ import annotations

import json

import numpy as np

from tools.stream_analysis import online_runtime as mod


NOZZLE_CENTER_PX = (110, 60)


def _blank_frame():
    return np.full((320, 220), 230, dtype=np.uint8)


def _frame_with_attached_stream(*, bottom_y: int = 170):
    frame = _blank_frame()
    frame[62:bottom_y, 96:124] = 20
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


def test_analyze_online_stream_frame_returns_measurement_for_valid_attached_stream():
    result = mod.analyze_online_stream_frame(
        frame_image=_frame_with_attached_stream(bottom_y=170),
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
    assert result["overlay"] is not None


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
    assert "detached_near_bottom_warning" in summary["warnings"]


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
