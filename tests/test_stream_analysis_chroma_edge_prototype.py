import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from tools.stream_analysis import online_chroma_edge_prototype as mod
from tools.stream_analysis import volume as volume_mod


def _rule(*, gray_headroom_px=30, delta_lab_chroma_max=-6.0, edge_bg_gap_min=55.0, continuity_min_support=3):
    return {
        "candidate_id": mod._candidate_id(
            gray_headroom_px=int(gray_headroom_px),
            delta_lab_chroma_max=float(delta_lab_chroma_max),
            edge_bg_gap_min=int(edge_bg_gap_min),
            continuity_min_support=int(continuity_min_support),
        ),
        "gray_headroom_px": int(gray_headroom_px),
        "delta_lab_chroma_max": float(delta_lab_chroma_max),
        "edge_bg_gap_min": int(edge_bg_gap_min),
        "continuity_min_support": int(continuity_min_support),
    }


def _feature_row(
    y_px: int,
    side: str,
    *,
    gray_headroom=10.0,
    delta_lab_chroma=-8.0,
    edge_bg_gap=60.0,
):
    current_x_px = 120 if side == "left" else 150
    return {
        "run_label": "BSA",
        "capture_id": "cap_000001",
        "capture_index": 1,
        "delay_from_emergence_us": 650,
        "y_px": int(y_px),
        "side": str(side),
        "current_x_px": int(current_x_px),
        "outside_x_px": int(current_x_px - 1 if side == "left" else current_x_px + 1),
        "outside_in_bounds": True,
        "contiguous_to_attached_mask": True,
        "is_currently_excluded": True,
        "gray_edge": 140,
        "gray_outside": 150,
        "gray_headroom": float(gray_headroom),
        "b_edge": 205,
        "g_edge": 145,
        "r_edge": 92,
        "b_outside": 210,
        "g_outside": 150,
        "r_outside": 100,
        "rb_chroma": 110.0,
        "blue_excess": 45.0,
        "edge_bg_gap": float(edge_bg_gap),
        "out_bg_gap": 60.0,
        "edge_lab_a": 14.0,
        "edge_lab_b": -33.0,
        "edge_lab_chroma": 35.8,
        "out_lab_a": 9.0,
        "out_lab_b": -22.0,
        "out_lab_chroma": 27.0,
        "delta_lab_chroma": float(delta_lab_chroma),
    }


def _edge_row(y_px: int, *, x_left=120, x_right=150):
    return {
        "y_px": int(y_px),
        "x_left_px": int(x_left),
        "x_right_px": int(x_right),
        "width_px": int(x_right - x_left + 1),
        "center_x_px": float(x_left + x_right) / 2.0,
    }


def _make_color_stream_frame(
    width: int,
    height: int,
    *,
    x_center: int,
    nozzle_y: int,
    add_halo: bool,
):
    image = np.full((height, width, 3), 245, dtype=np.uint8)
    cv2.rectangle(image, (x_center - 42, 22), (x_center + 42, 68), (95, 95, 95), thickness=-1)
    cv2.rectangle(image, (x_center - 8, 52), (x_center + 8, nozzle_y + 8), (35, 35, 35), thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 72), (28, 70), 0.0, 0.0, 360.0, (35, 35, 35), thickness=-1)
    cv2.rectangle(image, (x_center - 12, nozzle_y + 16), (x_center + 12, nozzle_y + 108), (220, 220, 220), thickness=-1)
    cv2.line(image, (x_center - 16, nozzle_y + 8), (x_center + 16, nozzle_y + 8), (18, 18, 18), thickness=3)
    if add_halo:
        cv2.ellipse(image, (x_center, nozzle_y + 72), (31, 73), 0.0, 0.0, 360.0, (235, 185, 135), thickness=2)
        cv2.line(image, (x_center - 14, nozzle_y + 18), (x_center - 14, nozzle_y + 104), (230, 175, 120), thickness=1)
        cv2.line(image, (x_center + 14, nozzle_y + 18), (x_center + 14, nozzle_y + 104), (230, 175, 120), thickness=1)
    return image


def test_row_side_gating_accepts_near_threshold_chromatic_pixel_with_support():
    rows = [_feature_row(200 + idx, "left") for idx in range(5)]
    evaluated = mod._evaluate_rule_on_row_side_features(rows, _rule())

    center_row = next(row for row in evaluated if int(row["y_px"]) == 202)
    assert center_row["base_gate_pass"] is True
    assert center_row["support_count"] >= 3
    assert center_row["moved"] is True
    assert int(center_row["move_outward_px"]) == 1
    assert int(center_row["corrected_x_px"]) == int(center_row["current_x_px"]) - 1


def test_row_side_gating_rejects_bright_neutral_pixel():
    rows = [_feature_row(200 + idx, "left", gray_headroom=15.0, delta_lab_chroma=-1.0, edge_bg_gap=18.0) for idx in range(5)]
    evaluated = mod._evaluate_rule_on_row_side_features(rows, _rule())

    assert all(row["base_gate_pass"] is False for row in evaluated)
    assert all(row["moved"] is False for row in evaluated)


def test_row_side_gating_rejects_isolated_pixel_without_continuity_support():
    rows = [_feature_row(200 + idx, "right", gray_headroom=50.0, delta_lab_chroma=-1.0, edge_bg_gap=18.0) for idx in range(5)]
    rows[2] = _feature_row(202, "right", gray_headroom=10.0, delta_lab_chroma=-8.0, edge_bg_gap=62.0)

    evaluated = mod._evaluate_rule_on_row_side_features(rows, _rule())
    center_row = next(row for row in evaluated if int(row["y_px"]) == 202)
    assert center_row["base_gate_pass"] is True
    assert center_row["support_count"] == 1
    assert center_row["moved"] is False


def test_row_side_gating_can_relax_continuity_when_rule_support_threshold_is_lowered():
    rows = [_feature_row(200 + idx, "right", gray_headroom=50.0, delta_lab_chroma=-1.0, edge_bg_gap=18.0) for idx in range(5)]
    rows[1] = _feature_row(201, "right", gray_headroom=10.0, delta_lab_chroma=-8.0, edge_bg_gap=60.0)
    rows[2] = _feature_row(202, "right", gray_headroom=10.0, delta_lab_chroma=-8.0, edge_bg_gap=62.0)

    evaluated = mod._evaluate_rule_on_row_side_features(rows, _rule(continuity_min_support=2))
    center_row = next(row for row in evaluated if int(row["y_px"]) == 202)
    assert center_row["support_count"] == 2
    assert center_row["moved"] is True


def test_lab_descriptor_metrics_capture_stronger_edge_chroma():
    edge = mod._lab_descriptor_metrics(np.asarray([205, 145, 92], dtype=np.uint8))
    outside = mod._lab_descriptor_metrics(np.asarray([215, 185, 165], dtype=np.uint8))

    assert edge["bg_gap"] > 0
    assert outside["bg_gap"] >= 0
    assert outside["lab_chroma"] < edge["lab_chroma"]


def test_apply_edge_correction_never_moves_more_than_one_pixel_per_side():
    edge_rows = [_edge_row(210)]
    decisions = [
        {
            "y_px": 210,
            "side": "left",
            "current_x_px": 120,
            "corrected_x_px": 119,
            "moved": True,
            "move_outward_px": 1,
        },
        {
            "y_px": 210,
            "side": "right",
            "current_x_px": 150,
            "corrected_x_px": 151,
            "moved": True,
            "move_outward_px": 1,
        },
    ]

    corrected = mod._apply_edge_correction(edge_rows, decisions, {"x0": 100, "x1": 200})
    assert corrected[0]["x_left_px"] == 119
    assert corrected[0]["x_right_px"] == 151
    assert corrected[0]["width_px"] == 33


def test_select_rule_picks_highest_bsa_candidate_among_water_guard_passes():
    summaries = [
        {
            "candidate_id": "a",
            "passes_water_guard": True,
            "bsa_mean_attached_delta_pct": 0.5,
            "water_mean_attached_delta_pct": 0.2,
            "water_max_attached_delta_pct": 0.9,
            "total_moved_row_side_count": 10,
        },
        {
            "candidate_id": "b",
            "passes_water_guard": True,
            "bsa_mean_attached_delta_pct": 0.8,
            "water_mean_attached_delta_pct": 0.4,
            "water_max_attached_delta_pct": 1.2,
            "total_moved_row_side_count": 12,
        },
        {
            "candidate_id": "c",
            "passes_water_guard": False,
            "bsa_mean_attached_delta_pct": 2.0,
            "water_mean_attached_delta_pct": 4.0,
            "water_max_attached_delta_pct": 6.0,
            "total_moved_row_side_count": 50,
        },
    ]

    selection = mod._select_rule(summaries)
    assert selection["selected_rule"]["candidate_id"] == "b"
    assert selection["rendered_rule"]["candidate_id"] == "b"
    assert selection["rendered_rule_kind"] == "selected_guard_passing"


def test_select_rule_returns_fallback_when_no_candidate_passes_water_guard():
    summaries = [
        {
            "candidate_id": "a",
            "passes_water_guard": False,
            "bsa_mean_attached_delta_pct": 0.6,
            "water_mean_attached_delta_pct": 1.8,
            "water_max_attached_delta_pct": 3.0,
            "total_moved_row_side_count": 8,
        },
        {
            "candidate_id": "b",
            "passes_water_guard": False,
            "bsa_mean_attached_delta_pct": 1.1,
            "water_mean_attached_delta_pct": 2.2,
            "water_max_attached_delta_pct": 2.7,
            "total_moved_row_side_count": 12,
        },
    ]

    selection = mod._select_rule(summaries)
    assert selection["selected_rule"] is None
    assert selection["fallback_rule"]["candidate_id"] == "b"
    assert selection["rendered_rule_kind"] == "fallback_exploratory"


def test_edge_correction_geometry_replay_matches_expected_volume_change():
    edge_rows = [_edge_row(210, x_left=120, x_right=150), _edge_row(211, x_left=121, x_right=151)]
    decisions = []
    for y_px, x_left, x_right in [(210, 120, 150), (211, 121, 151)]:
        decisions.extend(
            [
                {
                    "y_px": y_px,
                    "side": "left",
                    "current_x_px": x_left,
                    "corrected_x_px": x_left - 1,
                    "moved": True,
                    "move_outward_px": 1,
                },
                {
                    "y_px": y_px,
                    "side": "right",
                    "current_x_px": x_right,
                    "corrected_x_px": x_right + 1,
                    "moved": True,
                    "move_outward_px": 1,
                },
            ]
        )

    corrected = mod._apply_edge_correction(edge_rows, decisions, {"x0": 100, "x1": 200})
    current_volume = mod._edge_rows_volume_nl(edge_rows)
    corrected_volume = mod._edge_rows_volume_nl(corrected)
    expected_rows = [
        {**edge_rows[0], "x_left_px": 119, "x_right_px": 151, "width_px": 33, "center_x_px": 135.0},
        {**edge_rows[1], "x_left_px": 120, "x_right_px": 152, "width_px": 33, "center_x_px": 136.0},
    ]
    expected_volume = float(sum(volume_mod._row_volume_um3(row) for row in expected_rows)) / float(volume_mod.UM3_PER_NL)
    assert corrected_volume > current_volume
    assert corrected_volume == pytest.approx(expected_volume)


def test_export_online_chroma_edge_prototype_writes_expected_artifacts(tmp_path):
    pytest.importorskip("matplotlib")

    bsa_run = tmp_path / "bsa_run"
    water_run = tmp_path / "water_run"
    bsa_captures = bsa_run / "captures"
    water_captures = water_run / "captures"
    bsa_captures.mkdir(parents=True, exist_ok=True)
    water_captures.mkdir(parents=True, exist_ok=True)

    bsa_image = _make_color_stream_frame(360, 480, x_center=180, nozzle_y=110, add_halo=True)
    water_image = _make_color_stream_frame(360, 480, x_center=180, nozzle_y=110, add_halo=False)
    bsa_image_path = bsa_captures / "cap_000001_flow_frame.jpg"
    water_image_path = water_captures / "cap_000001_flow_frame.jpg"
    cv2.imwrite(str(bsa_image_path), bsa_image)
    cv2.imwrite(str(water_image_path), water_image)

    manifest_path = tmp_path / "comparison_manifest.json"
    manifest = {
        "analysis": "online_flow_contour_overlays",
        "output_root": str(tmp_path / "source"),
        "target_delays_from_emergence_us": [650],
        "bsa": {
            "label": "BSA",
            "run_dir": str(bsa_run),
            "emergence_time_us": 4700,
            "nozzle_center_px": [180, 110],
        },
        "water": {
            "label": "Water",
            "run_dir": str(water_run),
            "emergence_time_us": 4700,
            "nozzle_center_px": [180, 110],
        },
        "pairs": [
            {
                "target_delay_from_emergence_us": 650,
                "bsa": {
                    "capture_index": 1,
                    "capture_id": "cap_000001",
                    "delay_us": 5350,
                    "delay_from_emergence_us": 650,
                    "image_path": str(bsa_image_path),
                },
                "water": {
                    "capture_index": 1,
                    "capture_id": "cap_000001",
                    "delay_us": 5350,
                    "delay_from_emergence_us": 650,
                    "image_path": str(water_image_path),
                },
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    output_root = tmp_path / "prototype_outputs"
    payload = mod.export_online_chroma_edge_prototype(manifest_path, output_root=output_root)

    assert payload["analysis"] == "online_flow_chroma_edge_prototype_v2"
    assert payload["descriptor_family"] == "delta_lab_chroma_plus_edge_bg_gap"
    assert Path(payload["prototype_manifest_json"]).exists()
    assert Path(payload["paths"]["parameter_sweep_summary_csv"]).exists()
    assert Path(payload["paths"]["rule_selection_summary_json"]).exists()
    assert Path(payload["paths"]["matched_pair_before_after_contact_sheet_png"]).exists()

    bsa_frame = payload["frames"]["bsa"][0]
    water_frame = payload["frames"]["water"][0]
    assert "delta_lab_chroma_max" in payload["rendered_rule"]
    assert "edge_bg_gap_min" in payload["rendered_rule"]
    assert Path(bsa_frame["before_after_panel_png"]).exists()
    assert Path(bsa_frame["row_side_decisions_csv"]).exists()
    assert Path(bsa_frame["volume_comparison_json"]).exists()
    assert len(bsa_frame["profile_outputs"]) >= 1
    assert Path(bsa_frame["profile_outputs"][0]["plot_path"]).exists()
    assert Path(water_frame["before_after_panel_png"]).exists()
