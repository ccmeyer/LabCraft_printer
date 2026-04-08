from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tools.stream_analysis import fit as mod
from tools.stream_analysis import fov as fov_mod
from tests.test_stream_analysis_silhouette import _make_silhouette_experiment


def _frame_row(
    capture_index: int,
    *,
    delay_from_emergence_us: int | None,
    flash_delay_us: int,
    total_visible_volume_nl: float | None,
    trust_label: str,
    tracked_nozzle_y_px: float = 100.0,
):
    return {
        "run_id": "run_a",
        "capture_id": f"cap_{capture_index:06d}",
        "capture_index": capture_index,
        "flash_delay_us": flash_delay_us,
        "delay_from_emergence_us": delay_from_emergence_us,
        "tracked_nozzle_x_px": 180.0,
        "tracked_nozzle_y_px": tracked_nozzle_y_px,
        "tracked_confidence": 0.95,
        "raw_mode": "visible_nozzle_line",
        "final_mode": "visible_nozzle_line",
        "segment_id": 0,
        "shift_event_before": False,
        "silhouette_status": "ok",
        "failure_reason": None,
        "accepted_component_count": 1,
        "accepted_detached_component_count": 0,
        "attached_visible_volume_nl": total_visible_volume_nl,
        "detached_visible_volume_nl": 0.0 if total_visible_volume_nl is not None else None,
        "total_visible_volume_nl": total_visible_volume_nl,
        "volume_is_trusted": trust_label == fov_mod.TRUST_LABEL_TRUSTED,
        "volume_trust_label": trust_label,
        "accepted_fluid_near_fov_exit": trust_label == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        "fov_near_component_count": 1 if trust_label == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT else 0,
        "min_accepted_fluid_distance_from_bottom_px": 25 if trust_label == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT else 80,
        "fov_exit_triggered": False,
        "fov_exit_reason": None,
        "sample_frame": False,
    }


def _edge_rows_for_capture(
    capture_index: int,
    *,
    band_y0_px: int = 124,
    band_height_px: int = 40,
    width_px: int = 74,
):
    x_left = 180 - (width_px // 2)
    x_right = x_left + width_px - 1
    rows = []
    for y_px in range(band_y0_px, band_y0_px + band_height_px):
        rows.append(
            {
                "run_id": "run_a",
                "capture_id": f"cap_{capture_index:06d}",
                "capture_index": capture_index,
                "flash_delay_us": 4700 + (capture_index * 50),
                "component_id": "attached_primary",
                "component_role": "attached_primary",
                "component_rank": 0,
                "y_px": y_px,
                "x_left_px": x_left,
                "x_right_px": x_right,
                "width_px": width_px,
                "center_x_px": (x_left + x_right) / 2.0,
            }
        )
    return rows


def _feature_row(
    capture_index: int,
    *,
    delay_from_emergence_us: int,
    volume_nl: float,
    width_px: float | None,
    steady_candidate: bool = True,
):
    return {
        "capture_id": f"cap_{capture_index:06d}",
        "capture_index": capture_index,
        "delay_from_emergence_us": delay_from_emergence_us,
        "flash_delay_us": 4700 + (capture_index * 50),
        "total_visible_volume_nl": volume_nl,
        "attached_near_nozzle_width_median_px": width_px,
        "attached_near_nozzle_width_smoothed_px": width_px,
        "steady_candidate": steady_candidate,
        "volume_trust_label": fov_mod.TRUST_LABEL_TRUSTED,
    }


def _backfill_retry_feature_rows(*, backfill_volume_nl: float = 1.8):
    return [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=backfill_volume_nl, width_px=76.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=72.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=70.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=69.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=69.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=69.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=69.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.1, width_px=69.0),
        _feature_row(9, delay_from_emergence_us=900, volume_nl=9.3, width_px=69.0),
    ]


def test_near_nozzle_width_metrics_extracts_band_statistics():
    frame_row = {"tracked_nozzle_y_px": 100.0}
    attached_edge_rows = _edge_rows_for_capture(1, width_px=72)

    metrics = mod._near_nozzle_width_metrics(
        frame_row,
        attached_edge_rows,
        near_nozzle_band_top_px=24,
        near_nozzle_band_height_px=40,
        min_band_valid_rows=24,
    )

    assert metrics["attached_near_nozzle_width_median_px"] == 72.0
    assert metrics["attached_near_nozzle_width_iqr_px"] == 0.0
    assert metrics["attached_near_nozzle_band_valid_row_count"] == 40
    assert metrics["attached_near_nozzle_band_y0_px"] == 124
    assert metrics["attached_near_nozzle_band_y1_px"] == 164


def test_near_nozzle_width_metrics_invalidates_when_too_few_rows():
    frame_row = {"tracked_nozzle_y_px": 100.0}
    attached_edge_rows = _edge_rows_for_capture(1, band_height_px=10, width_px=72)

    metrics = mod._near_nozzle_width_metrics(
        frame_row,
        attached_edge_rows,
        near_nozzle_band_top_px=24,
        near_nozzle_band_height_px=40,
        min_band_valid_rows=24,
    )

    assert metrics["attached_near_nozzle_width_median_px"] is None
    assert metrics["attached_near_nozzle_width_iqr_px"] is None
    assert metrics["attached_near_nozzle_band_valid_row_count"] == 10


def test_steady_window_metrics_fits_noisy_linear_trace():
    window_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.02, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.01, width_px=74.5),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=2.98, width_px=74.1),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.04, width_px=73.8),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.00, width_px=74.2),
    ]

    metrics = mod._steady_window_metrics(
        window_rows,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
    )

    assert metrics is not None
    assert metrics["steady_rate_nl_per_us"] == pytest.approx(0.010, rel=0.05)
    assert metrics["steady_r2"] >= 0.998
    assert metrics["steady_nrmse"] <= 0.03
    assert metrics["steady_fit_ok"] is True


def test_find_steady_window_uses_earliest_qualifying_block():
    feature_rows = []
    for capture_index in range(1, 9):
        feature_rows.append(
            _feature_row(
                capture_index,
                delay_from_emergence_us=capture_index * 100,
                volume_nl=float(capture_index),
                width_px=74.0,
                steady_candidate=True,
            )
        )
    feature_rows.append(
        _feature_row(
            9,
            delay_from_emergence_us=900,
            volume_nl=9.0,
            width_px=None,
            steady_candidate=False,
        )
    )
    for capture_index in range(10, 19):
        feature_rows.append(
            _feature_row(
                capture_index,
                delay_from_emergence_us=capture_index * 100,
                volume_nl=float(capture_index),
                width_px=75.0,
                steady_candidate=True,
            )
        )

    steady_fit = mod._find_steady_window(
        feature_rows,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.985,
        steady_fit_nrmse_max=0.03,
    )

    assert steady_fit["steady_fit_status"] == "ok"
    assert steady_fit["steady_start_capture_index"] == 1
    assert steady_fit["steady_end_capture_index"] == 8


def test_steady_fit_from_payload_reconstructs_ci95_from_cached_steady_points():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
    ]

    steady_fit = mod._steady_fit_from_payload(
        feature_rows,
        {
            "steady_fit_status": "ok",
            "steady_capture_indices": [1, 2, 3, 4],
            "steady_start_capture_index": 1,
            "steady_end_capture_index": 4,
            "steady_rate_nl_per_us": 0.01,
            "steady_intercept_nl": 0.0,
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "steady_width_span_px": 0.0,
            "steady_width_tolerance_px": 4.0,
        },
    )

    assert steady_fit["steady_capture_indices"] == [1, 2, 3, 4]
    assert steady_fit["steady_fit_point_count"] == 4
    assert steady_fit["steady_rate_confidence_status"] == "ok"
    assert steady_fit["steady_rate_ci95_contains_central"] is True
    assert steady_fit["steady_rate_ci95_low_nl_per_us"] == pytest.approx(0.01, rel=1e-6)
    assert steady_fit["steady_rate_ci95_high_nl_per_us"] == pytest.approx(0.01, rel=1e-6)
    assert steady_fit["steady_rate_ci95_relative_width"] == pytest.approx(0.0, rel=1e-6)


def test_steady_fit_from_payload_falls_back_to_contiguous_capture_range():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
    ]

    steady_fit = mod._steady_fit_from_payload(
        feature_rows,
        {
            "steady_fit_status": "ok",
            "steady_capture_indices": [],
            "steady_start_capture_index": 2,
            "steady_end_capture_index": 4,
            "steady_rate_nl_per_us": 0.01,
            "steady_intercept_nl": 0.0,
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "steady_width_span_px": 0.0,
            "steady_width_tolerance_px": 4.0,
        },
    )

    assert steady_fit["steady_capture_indices"] == [2, 3, 4]
    assert steady_fit["flow_fit_capture_indices"] == [2, 3, 4]
    assert steady_fit["positions"] == [1, 2, 3]
    assert steady_fit["steady_fit_point_count"] == 3
    assert steady_fit["steady_rate_confidence_status"] == "ok"


def test_steady_fit_from_payload_uses_split_plateau_and_flow_fit_fields():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=80.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=80.0),
    ]

    steady_fit = mod._steady_fit_from_payload(
        feature_rows,
        {
            "steady_fit_status": "ok",
            "plateau_capture_indices": [2, 3, 4],
            "plateau_point_count": 3,
            "steady_capture_indices": [2, 3, 4],
            "steady_start_capture_index": 2,
            "steady_end_capture_index": 4,
            "flow_fit_capture_indices": [2, 3, 4, 5, 6],
            "flow_fit_start_capture_index": 2,
            "flow_fit_end_capture_index": 6,
            "flow_fit_point_count": 5,
            "flow_fit_eligible_point_count": 5,
            "flow_fit_outlier_prune_status": "kept_below_local_deviation_threshold",
            "steady_rate_nl_per_us": 0.01,
            "steady_intercept_nl": 0.0,
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "steady_width_span_px": 0.0,
            "steady_width_tolerance_px": 4.0,
        },
    )

    assert steady_fit["positions"] == [1, 2, 3]
    assert steady_fit["plateau_positions"] == [1, 2, 3]
    assert steady_fit["flow_fit_positions"] == [1, 2, 3, 4, 5]
    assert steady_fit["steady_capture_indices"] == [2, 3, 4]
    assert steady_fit["flow_fit_capture_indices"] == [2, 3, 4, 5, 6]
    assert steady_fit["plateau_point_count"] == 3
    assert steady_fit["flow_fit_point_count"] == 5
    assert steady_fit["steady_fit_point_count"] == 5
    assert steady_fit["steady_rate_confidence_status"] == "ok"
    assert steady_fit["steady_rate_ci95_contains_central"] is True


def test_steady_fit_from_payload_reports_central_rate_mismatch_without_widening_ci95():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
    ]

    steady_fit = mod._steady_fit_from_payload(
        feature_rows,
        {
            "steady_fit_status": "ok",
            "steady_capture_indices": [1, 2, 3, 4],
            "steady_start_capture_index": 1,
            "steady_end_capture_index": 4,
            "steady_rate_nl_per_us": 0.02,
            "steady_intercept_nl": 0.0,
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "steady_width_span_px": 0.0,
            "steady_width_tolerance_px": 4.0,
        },
    )

    assert steady_fit["steady_rate_confidence_status"] == "warning_central_rate_mismatch"
    assert steady_fit["steady_rate_ci95_contains_central"] is False
    assert steady_fit["steady_rate_ci95_low_nl_per_us"] == pytest.approx(0.01, rel=1e-6)
    assert steady_fit["steady_rate_ci95_high_nl_per_us"] == pytest.approx(0.01, rel=1e-6)
    assert steady_fit["steady_rate_ci95_relative_width"] == pytest.approx(0.0, rel=1e-6)


def test_steady_fit_confidence_from_points_orders_reversed_ci_bounds(monkeypatch):
    monkeypatch.setattr(
        mod.stats,
        "theilslopes",
        lambda *_args, **_kwargs: (0.01, 0.0, 0.012, 0.008),
    )

    confidence = mod._steady_fit_confidence_from_points(
        [(100.0, 1.0), (200.0, 2.0), (300.0, 3.0)],
        central_rate=0.01,
    )

    assert confidence["steady_rate_ci95_low_nl_per_us"] == pytest.approx(0.008, rel=1e-6)
    assert confidence["steady_rate_ci95_high_nl_per_us"] == pytest.approx(0.012, rel=1e-6)
    assert confidence["steady_rate_ci95_relative_width"] == pytest.approx(0.4, rel=1e-6)
    assert confidence["steady_rate_ci95_contains_central"] is True
    assert confidence["steady_rate_confidence_status"] == "ok"


def test_steady_fit_ci_band_points_anchor_to_steady_window_midpoint():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=80.0),
    ]

    steady_fit = {
        "steady_fit_status": "ok",
        "positions": [1, 2, 3],
        "steady_rate_nl_per_us": 0.01,
        "steady_intercept_nl": 0.0,
        "steady_rate_ci95_low_nl_per_us": 0.009,
        "steady_rate_ci95_high_nl_per_us": 0.011,
    }

    ci_points = mod._steady_fit_ci_band_points(
        feature_rows,
        steady_fit,
        plot_x_values=[100.0, 200.0, 300.0, 400.0, 500.0],
    )

    assert ci_points[0] == pytest.approx((200.0, 1.9, 2.1), rel=1e-6)
    assert ci_points[1] == pytest.approx((300.0, 3.0, 3.0), rel=1e-6)
    assert ci_points[-1] == pytest.approx((500.0, 4.8, 5.2), rel=1e-6)


def test_recompute_steady_fit_excludes_last_trusted_frames_before_fov_exit():
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=80.0)
        for capture_index in range(1, 9)
    ] + [
        _feature_row(9, delay_from_emergence_us=900, volume_nl=9.25, width_px=80.0),
        _feature_row(10, delay_from_emergence_us=1000, volume_nl=10.45, width_px=80.0),
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=11,
        exclude_last_trusted_frames=2,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.05,
    )

    assert steady_fit["steady_fit_status"] == "ok"
    assert steady_fit["steady_fit_mode"] == "recompute"
    assert steady_fit["steady_capture_indices"] == [1, 2, 3, 4]
    assert steady_fit["plateau_capture_indices"] == [1, 2, 3, 4]
    assert steady_fit["flow_fit_capture_indices"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert steady_fit["steady_end_capture_index"] == 4
    assert steady_fit["flow_fit_end_capture_index"] == 8
    assert steady_fit["plateau_point_count"] == 4
    assert steady_fit["flow_fit_point_count"] == 8
    assert steady_fit["flow_fit_eligible_point_count"] == 8
    assert steady_fit["flow_fit_backfill_point_count"] == 0
    assert steady_fit["steady_fit_point_count"] == 8
    assert steady_fit["excluded_tail_trusted_capture_indices"] == [9, 10]
    assert steady_fit["steady_fit_excluded_tail_trusted_frame_count"] == 2


def test_recompute_steady_fit_rejects_final_flow_fit_below_thresholds():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=8.0, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=80.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=80.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=80.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=80.0),
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=None,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.9999,
        steady_fit_nrmse_max=0.0001,
    )

    assert steady_fit["steady_fit_status"] == "unresolved_quality_thresholds"
    assert steady_fit["plateau_capture_indices"] == [1, 2, 3, 4]
    assert steady_fit["flow_fit_capture_indices"] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert steady_fit["flow_fit_start_capture_index"] == 1
    assert steady_fit["flow_fit_end_capture_index"] == 8
    assert steady_fit["steady_fit_point_count"] == 8
    assert steady_fit["steady_rate_nl_per_us"] is None
    assert steady_fit["steady_intercept_nl"] is None
    assert steady_fit["steady_rate_ci95_low_nl_per_us"] is None
    assert steady_fit["steady_rate_ci95_high_nl_per_us"] is None
    assert steady_fit["steady_rate_confidence_status"] == "unresolved_quality_thresholds"
    assert steady_fit["steady_r2"] < 0.8
    assert steady_fit["steady_nrmse"] > 0.1


def test_recompute_steady_fit_sources_central_rate_from_flow_fit_window_not_plateau_seed():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=0.9, width_px=96.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.6, width_px=88.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=2.8, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=3.7, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=4.6, width_px=80.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=5.5, width_px=80.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=80.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.5, width_px=80.0),
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=9,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        flow_fit_backfill_max_frames=1,
        flow_fit_backfill_width_delta_px=8.0,
        flow_fit_backfill_monotonic_slack_px=0.75,
        steady_fit_r2_min=0.90,
        steady_fit_nrmse_max=0.10,
    )

    plateau_rows = [feature_rows[index] for index in [2, 3, 4, 5]]
    flow_rows = [feature_rows[index] for index in [1, 2, 3, 4, 5, 6, 7]]
    plateau_metrics = mod._fit_window_metrics(plateau_rows)
    flow_metrics = mod._fit_window_metrics(flow_rows)

    assert steady_fit["steady_start_capture_index"] == 3
    assert steady_fit["steady_end_capture_index"] == 6
    assert steady_fit["flow_fit_start_capture_index"] == 2
    assert steady_fit["flow_fit_end_capture_index"] == 8
    assert steady_fit["flow_fit_backfill_point_count"] == 1
    assert steady_fit["steady_rate_nl_per_us"] == pytest.approx(
        flow_metrics["steady_rate_nl_per_us"], rel=1e-9
    )
    assert steady_fit["steady_nrmse"] == pytest.approx(flow_metrics["steady_nrmse"], rel=1e-9)
    assert steady_fit["steady_nrmse"] != pytest.approx(
        plateau_metrics["steady_nrmse"], rel=1e-4
    )


def test_recompute_steady_fit_retries_without_backfill_when_primary_window_fails_quality():
    feature_rows = _backfill_retry_feature_rows(backfill_volume_nl=1.8)

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=10,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        flow_fit_backfill_max_frames=1,
        flow_fit_backfill_width_delta_px=8.0,
        flow_fit_backfill_monotonic_slack_px=0.75,
        steady_fit_r2_min=0.985,
        steady_fit_nrmse_max=0.03,
    )

    retry_metrics = mod._fit_window_metrics(feature_rows[1:])

    assert steady_fit["steady_fit_status"] == "ok"
    assert steady_fit["steady_start_capture_index"] == 2
    assert steady_fit["steady_end_capture_index"] == 5
    assert steady_fit["plateau_capture_indices"] == [2, 3, 4, 5]
    assert steady_fit["flow_fit_capture_indices"] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert steady_fit["flow_fit_backfill_point_count"] == 0
    assert steady_fit["flow_fit_start_capture_index"] == 2
    assert steady_fit["flow_fit_end_capture_index"] == 9
    assert steady_fit["steady_rate_nl_per_us"] == pytest.approx(
        retry_metrics["steady_rate_nl_per_us"], rel=1e-9
    )
    assert steady_fit["steady_r2"] == pytest.approx(retry_metrics["steady_r2"], rel=1e-9)
    assert steady_fit["steady_nrmse"] == pytest.approx(retry_metrics["steady_nrmse"], rel=1e-9)
    assert steady_fit["steady_rate_ci95_low_nl_per_us"] is not None
    assert steady_fit["steady_rate_ci95_high_nl_per_us"] is not None
    assert steady_fit["steady_rate_confidence_status"] == "ok"


def test_recompute_steady_fit_keeps_backfill_when_primary_window_already_passes_quality():
    feature_rows = _backfill_retry_feature_rows(backfill_volume_nl=1.5)

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=10,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        flow_fit_backfill_max_frames=1,
        flow_fit_backfill_width_delta_px=8.0,
        flow_fit_backfill_monotonic_slack_px=0.75,
        steady_fit_r2_min=0.985,
        steady_fit_nrmse_max=0.03,
    )

    primary_metrics = mod._fit_window_metrics(feature_rows)

    assert steady_fit["steady_fit_status"] == "ok"
    assert steady_fit["flow_fit_capture_indices"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert steady_fit["flow_fit_backfill_point_count"] == 1
    assert steady_fit["flow_fit_start_capture_index"] == 1
    assert steady_fit["steady_rate_nl_per_us"] == pytest.approx(
        primary_metrics["steady_rate_nl_per_us"], rel=1e-9
    )
    assert steady_fit["steady_nrmse"] == pytest.approx(primary_metrics["steady_nrmse"], rel=1e-9)


def test_recompute_steady_fit_keeps_primary_failure_when_retry_without_backfill_also_fails():
    feature_rows = _backfill_retry_feature_rows(backfill_volume_nl=1.8)

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=10,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        flow_fit_backfill_max_frames=1,
        flow_fit_backfill_width_delta_px=8.0,
        flow_fit_backfill_monotonic_slack_px=0.75,
        steady_fit_r2_min=0.9999,
        steady_fit_nrmse_max=0.0001,
    )

    assert steady_fit["steady_fit_status"] == "unresolved_quality_thresholds"
    assert steady_fit["flow_fit_capture_indices"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert steady_fit["flow_fit_backfill_point_count"] == 1
    assert steady_fit["steady_rate_nl_per_us"] is None
    assert steady_fit["steady_rate_ci95_low_nl_per_us"] is None
    assert steady_fit["steady_rate_confidence_status"] == "unresolved_quality_thresholds"


def test_recompute_steady_fit_uses_first_qualifying_plateau_seed_and_extends_flow_fit():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=98.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=92.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=80.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=80.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=80.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=80.0),
        _feature_row(9, delay_from_emergence_us=900, volume_nl=9.0, width_px=80.0),
        _feature_row(10, delay_from_emergence_us=1000, volume_nl=10.0, width_px=80.0),
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=11,
        exclude_last_trusted_frames=2,
        min_steady_frames=6,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.08,
    )

    assert steady_fit["steady_fit_status"] == "ok"
    assert steady_fit["steady_start_capture_index"] == 3
    assert steady_fit["steady_end_capture_index"] == 8
    assert steady_fit["plateau_capture_indices"] == [3, 4, 5, 6, 7, 8]
    assert steady_fit["flow_fit_start_capture_index"] == 3
    assert steady_fit["flow_fit_end_capture_index"] == 8
    assert steady_fit["flow_fit_capture_indices"] == [3, 4, 5, 6, 7, 8]
    assert steady_fit["steady_fit_candidate_window_count"] == 3
    assert steady_fit["steady_fit_selection_score"] is None
    assert steady_fit["flow_fit_outlier_prune_status"] == "kept_min_points_only"
    assert steady_fit["steady_fit_first_last_residual_delta_nl"] == pytest.approx(0.0, abs=1e-6)


def test_recompute_steady_fit_backfills_earlier_settling_points_and_stops_on_first_violation():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=95.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=89.5),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=87.5),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=80.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=80.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=80.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=80.0),
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=9,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        flow_fit_backfill_max_frames=3,
        flow_fit_backfill_width_delta_px=8.0,
        flow_fit_backfill_monotonic_slack_px=0.75,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.08,
    )

    assert steady_fit["plateau_capture_indices"] == [4, 5, 6, 7]
    assert steady_fit["flow_fit_capture_indices"] == [3, 4, 5, 6, 7, 8]
    assert steady_fit["flow_fit_backfill_point_count"] == 1
    assert steady_fit["flow_fit_start_capture_index"] == 3
    assert steady_fit["steady_start_capture_index"] == 4


def test_recompute_steady_fit_keeps_plateau_end_as_tail_search_anchor():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=79.5),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=72.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=70.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=68.0),
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=9,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.08,
    )
    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=9,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )

    assert steady_fit["steady_end_capture_index"] == 4
    assert steady_fit["flow_fit_end_capture_index"] == 8
    assert tail_onset["tail_onset_status"] == "before_fov_exit"
    assert tail_onset["tail_detection_mode"] == "confirmed_persistent"
    assert tail_onset["tail_confirmation_capture_index"] == 6
    assert tail_onset["tail_start_capture_index"] == 6


def test_recompute_steady_fit_drops_single_isolated_interior_outlier():
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=80.0)
        for capture_index in range(1, 6)
    ] + [
        _feature_row(6, delay_from_emergence_us=600, volume_nl=12.0, width_px=80.0),
    ] + [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=80.0)
        for capture_index in range(7, 11)
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=11,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.08,
    )

    assert steady_fit["steady_fit_status"] == "ok"
    assert steady_fit["flow_fit_outlier_prune_status"] == "dropped_isolated_point"
    assert steady_fit["flow_fit_dropped_outlier_capture_index"] == 6
    assert steady_fit["flow_fit_capture_indices"] == [1, 2, 3, 4, 5, 7, 8, 9, 10]
    assert steady_fit["flow_fit_eligible_point_count"] == 10
    assert steady_fit["flow_fit_point_count"] == 9
    assert steady_fit["plateau_capture_indices"] == [1, 2, 3, 4]
    assert steady_fit["steady_fit_point_count"] == 9


def test_recompute_steady_fit_keeps_all_points_when_outlier_not_unique_enough(monkeypatch):
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=80.0)
        for capture_index in range(1, 11)
    ]
    monkeypatch.setattr(
        mod,
        "_local_interpolation_deviation_candidates",
        lambda _feature_rows, _positions: [
            {
                "offset": 3,
                "position": 3,
                "capture_index": 4,
                "delay_from_emergence_us": 400,
                "local_deviation_nl": 4.0,
                "abs_local_deviation_nl": 4.0,
            },
            {
                "offset": 7,
                "position": 7,
                "capture_index": 8,
                "delay_from_emergence_us": 800,
                "local_deviation_nl": -4.0,
                "abs_local_deviation_nl": 4.0,
            },
            {
                "offset": 5,
                "position": 5,
                "capture_index": 6,
                "delay_from_emergence_us": 600,
                "local_deviation_nl": 0.5,
                "abs_local_deviation_nl": 0.5,
            },
        ],
    )

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=11,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.08,
    )

    assert steady_fit["flow_fit_outlier_prune_status"] == "kept_not_unique_enough"
    assert steady_fit["flow_fit_dropped_outlier_capture_index"] is None
    assert steady_fit["flow_fit_capture_indices"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_recompute_steady_fit_keeps_all_points_when_deviation_below_threshold():
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=80.0)
        for capture_index in range(1, 6)
    ] + [
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.4, width_px=80.0),
    ] + [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=80.0)
        for capture_index in range(7, 11)
    ]

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=11,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.08,
    )

    assert steady_fit["flow_fit_outlier_prune_status"] == "kept_below_local_deviation_threshold"
    assert steady_fit["flow_fit_dropped_outlier_capture_index"] is None


def test_recompute_steady_fit_keeps_all_points_when_prune_would_break_min_points():
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=80.0)
        for capture_index in range(1, 5)
    ]
    feature_rows[2]["total_visible_volume_nl"] = 8.0

    steady_fit = mod._recompute_steady_fit_from_feature_rows(
        feature_rows,
        first_untrusted_capture_index=5,
        exclude_last_trusted_frames=0,
        min_steady_frames=4,
        steady_width_tol_frac=0.08,
        steady_width_tol_px=4.0,
        steady_fit_r2_min=0.98,
        steady_fit_nrmse_max=0.08,
    )

    assert steady_fit["flow_fit_outlier_prune_status"] == "kept_min_points_only"
    assert steady_fit["flow_fit_dropped_outlier_capture_index"] is None


def test_find_tail_onset_uses_first_persistent_drop_after_steady_window():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=75.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=75.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=75.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=75.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=74.5),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=73.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=68.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=67.5),
        _feature_row(9, delay_from_emergence_us=900, volume_nl=9.0, width_px=66.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 4,
        "steady_width_plateau_px": 75.0,
    }

    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=5,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )

    assert tail_onset["tail_onset_status"] == "ok"
    assert tail_onset["tail_detection_mode"] == "confirmed_persistent"
    assert tail_onset["tail_confirmation_capture_index"] == 7
    assert tail_onset["tail_start_selection_mode"] == "direct_backtrack"
    assert tail_onset["preliminary_tail_start_capture_index"] == 6
    assert tail_onset["direct_final_tail_start_capture_index"] == 6
    assert tail_onset["tail_shoulder_end_capture_index"] is None
    assert tail_onset["tail_start_capture_index"] == 6
    assert tail_onset["tail_start_delay_from_emergence_us"] == 600


def test_find_tail_onset_backtracks_to_start_of_decline_episode():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=79.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=77.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=74.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=62.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=50.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 2,
        "steady_width_plateau_px": 80.0,
    }

    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=4,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )

    assert tail_onset["tail_confirmation_capture_index"] == 7
    assert tail_onset["tail_start_selection_mode"] == "direct_backtrack"
    assert tail_onset["preliminary_tail_start_capture_index"] == 4
    assert tail_onset["preliminary_tail_start_delay_from_emergence_us"] == 400
    assert tail_onset["direct_final_tail_start_capture_index"] == 5
    assert tail_onset["direct_final_tail_start_delay_from_emergence_us"] == 500
    assert tail_onset["tail_shoulder_end_capture_index"] is None
    assert tail_onset["tail_start_capture_index"] == 5
    assert tail_onset["tail_start_delay_from_emergence_us"] == 500


def test_find_tail_onset_adjusts_to_end_of_long_flat_shoulder():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=74.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=74.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=74.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=73.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=73.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=73.0),
        _feature_row(9, delay_from_emergence_us=900, volume_nl=9.0, width_px=73.0),
        _feature_row(10, delay_from_emergence_us=1000, volume_nl=10.0, width_px=73.0),
        _feature_row(11, delay_from_emergence_us=1100, volume_nl=11.0, width_px=72.0),
        _feature_row(12, delay_from_emergence_us=1200, volume_nl=12.0, width_px=70.0),
        _feature_row(13, delay_from_emergence_us=1300, volume_nl=13.0, width_px=68.0),
        _feature_row(14, delay_from_emergence_us=1400, volume_nl=14.0, width_px=64.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 4,
        "steady_width_plateau_px": 74.0,
    }

    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=4,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )

    assert tail_onset["tail_confirmation_capture_index"] == 13
    assert tail_onset["tail_start_selection_mode"] == "shoulder_adjusted"
    assert tail_onset["preliminary_tail_start_capture_index"] == 6
    assert tail_onset["direct_final_tail_start_capture_index"] == 11
    assert tail_onset["tail_shoulder_end_capture_index"] == 11
    assert tail_onset["tail_start_capture_index"] == 12
    assert tail_onset["tail_start_delay_from_emergence_us"] == 1200


def test_find_tail_onset_uses_truncated_width_loss_fallback():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=79.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=77.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=74.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=62.0),
        {
            **_feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=50.0),
            "attached_near_nozzle_width_smoothed_px": 50.0,
        },
        {
            **_feature_row(9, delay_from_emergence_us=900, volume_nl=9.0, width_px=None),
            "attached_near_nozzle_width_smoothed_px": None,
            "attached_near_nozzle_width_median_px": None,
        },
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 2,
        "steady_width_plateau_px": 80.0,
    }

    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=3,
        tail_drop_frac=0.08,
        tail_persist_frames=3,
    )

    assert tail_onset["tail_onset_status"] == "ok"
    assert tail_onset["tail_detection_mode"] == "confirmed_truncated_width_loss"
    assert tail_onset["tail_confirmation_capture_index"] == 7
    assert tail_onset["tail_start_selection_mode"] == "direct_backtrack"
    assert tail_onset["preliminary_tail_start_capture_index"] == 4
    assert tail_onset["direct_final_tail_start_capture_index"] == 5
    assert tail_onset["tail_shoulder_end_capture_index"] is None
    assert tail_onset["tail_start_capture_index"] == 5


def test_find_tail_onset_ignores_short_noisy_flat_patch():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=74.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=74.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=74.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=73.5),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=73.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=73.0),
        _feature_row(9, delay_from_emergence_us=900, volume_nl=9.0, width_px=73.0),
        _feature_row(10, delay_from_emergence_us=1000, volume_nl=10.0, width_px=70.0),
        _feature_row(11, delay_from_emergence_us=1100, volume_nl=11.0, width_px=68.0),
        _feature_row(12, delay_from_emergence_us=1200, volume_nl=12.0, width_px=64.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 4,
        "steady_width_plateau_px": 74.0,
    }

    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=4,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )

    assert tail_onset["tail_confirmation_capture_index"] == 11
    assert tail_onset["tail_start_selection_mode"] == "direct_backtrack"
    assert tail_onset["preliminary_tail_start_capture_index"] == 7
    assert tail_onset["direct_final_tail_start_capture_index"] == 10
    assert tail_onset["tail_shoulder_end_capture_index"] is None
    assert tail_onset["tail_start_capture_index"] == 10


def test_find_tail_onset_stays_unresolved_when_final_widths_never_cross_threshold():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=79.6),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=79.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=78.0),
        {
            **_feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=None),
            "attached_near_nozzle_width_smoothed_px": None,
            "attached_near_nozzle_width_median_px": None,
        },
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 2,
        "steady_width_plateau_px": 80.0,
    }

    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=4,
        tail_drop_frac=0.08,
        tail_persist_frames=3,
    )

    assert tail_onset["tail_onset_status"] == "unresolved"
    assert tail_onset["tail_detection_mode"] == "unresolved"
    assert tail_onset["tail_confirmation_capture_index"] is None
    assert tail_onset["preliminary_tail_start_capture_index"] is None
    assert tail_onset["direct_final_tail_start_capture_index"] is None
    assert tail_onset["tail_start_capture_index"] is None


def test_tail_descriptor_context_ignores_early_pre_steady_shrink_peak():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=100.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=60.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=100.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=100.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=100.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=96.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=84.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=60.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 5,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_width_threshold_px": 80.0,
    }

    all_shrink_points = mod._normalized_width_shrink_rate_points(feature_rows, steady_fit)
    global_peak_delay_us = max(all_shrink_points, key=lambda point: float(point[1]))[0]
    context = mod._tail_descriptor_context(feature_rows, steady_fit, tail_onset)

    assert global_peak_delay_us < 500.0
    assert context["tail_peak_shrink_rate_delay_us"] > 500.0


def test_tail_candidate_descriptor_row_reports_expected_drop_metrics():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=100.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=100.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=100.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=90.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=80.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=60.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_width_threshold_px": 80.0,
    }

    context = mod._tail_descriptor_context(feature_rows, steady_fit, tail_onset)
    candidate_row = mod._tail_candidate_descriptor_row(
        feature_rows,
        3,
        candidate_window_kind="direct_backtrack",
        context=context,
        legacy_capture_index=4,
    )

    assert candidate_row["capture_index"] == 4
    assert candidate_row["delay_from_emergence_us"] == pytest.approx(400.0, rel=1e-6)
    assert candidate_row["drop_frac"] == pytest.approx(0.1, rel=1e-6)
    assert candidate_row["drop_to_threshold_frac"] == pytest.approx(0.5, rel=1e-6)
    assert candidate_row["tail_peak_lead_us"] == pytest.approx(
        context["tail_peak_shrink_rate_delay_us"] - 400.0,
        rel=1e-6,
    )
    assert candidate_row["is_legacy_anchor"] is True


def test_select_best_tail_score_candidate_prefers_earliest_capture_on_tie():
    best = mod._select_best_tail_score_candidate(
        [
            {"capture_index": 5, "position": 5, "score_total": 1.0},
            {"capture_index": 4, "position": 4, "score_total": 1.0},
            {"capture_index": 6, "position": 6, "score_total": 1.2},
        ]
    )

    assert best["capture_index"] == 4
    assert best["position"] == 4


def test_refine_tail_onset_for_review_scores_direct_candidates(monkeypatch):
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=100.0)
        for capture_index in range(1, 7)
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_start_selection_mode": "direct_backtrack",
        "direct_final_tail_start_capture_index": 4,
        "direct_final_tail_start_delay_from_emergence_us": 400,
        "direct_final_tail_start_position": 3,
        "tail_confirmation_capture_index": 6,
        "tail_confirmation_delay_from_emergence_us": 600,
        "tail_confirmation_position": 5,
        "tail_start_capture_index": 4,
        "tail_start_delay_from_emergence_us": 400,
        "tail_start_position": 3,
        "tail_onset_status": "ok",
        "tail_width_threshold_px": 80.0,
    }

    monkeypatch.setattr(
        mod,
        "_tail_descriptor_context",
        lambda *_args, **_kwargs: {
            "tail_peak_shrink_rate_norm_per_ms": 1.0,
            "tail_peak_shrink_rate_delay_us": 900.0,
        },
    )

    descriptor_by_position = {
        3: {
            "candidate_window_kind": "direct_backtrack",
            "position": 3,
            "capture_index": 4,
            "delay_from_emergence_us": 400.0,
            "width_px": 90.0,
            "drop_frac": 0.10,
            "drop_to_threshold_frac": 0.50,
            "shrink_rate_norm_per_ms": 0.20,
            "shrink_rate_ratio": 0.20,
            "tail_peak_lead_us": 500.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": True,
        },
        4: {
            "candidate_window_kind": "direct_backtrack",
            "position": 4,
            "capture_index": 5,
            "delay_from_emergence_us": 500.0,
            "width_px": 96.6,
            "drop_frac": 0.034,
            "drop_to_threshold_frac": 0.17,
            "shrink_rate_norm_per_ms": 0.117,
            "shrink_rate_ratio": 0.117,
            "tail_peak_lead_us": 223.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        5: {
            "candidate_window_kind": "direct_backtrack",
            "position": 5,
            "capture_index": 6,
            "delay_from_emergence_us": 600.0,
            "width_px": 80.0,
            "drop_frac": 0.20,
            "drop_to_threshold_frac": 1.0,
            "shrink_rate_norm_per_ms": 0.60,
            "shrink_rate_ratio": 0.60,
            "tail_peak_lead_us": 300.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
    }
    monkeypatch.setattr(
        mod,
        "_tail_candidate_descriptor_row",
        lambda _feature_rows, position, **_kwargs: dict(descriptor_by_position[int(position)]),
    )

    refined, candidate_rows = mod._refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=3,
        tail_start_mode=mod.TAIL_START_MODE_DESCRIPTOR_SCORE,
        tail_direct_target_drop_to_threshold_frac=0.171,
        tail_direct_target_peak_lead_us=223.0,
        tail_direct_target_shrink_rate_ratio=0.117,
        tail_shoulder_target_drop_to_threshold_frac=0.195,
        tail_shoulder_target_peak_lead_us=244.0,
        tail_shoulder_target_shrink_rate_ratio=0.107,
        tail_score_drop_weight=3.0,
        tail_score_peak_lead_weight=1.5,
        tail_score_shrink_rate_weight=1.0,
        tail_score_drop_scale=0.08,
        tail_score_peak_lead_scale_us=60.0,
        tail_score_shrink_rate_scale=0.04,
        tail_unified_band_drop_min=0.15,
        tail_unified_band_drop_max=0.35,
        tail_unified_band_peak_lead_min_us=180.0,
        tail_unified_band_peak_lead_max_us=320.0,
        tail_unified_band_shrink_rate_ratio_min=0.05,
        tail_unified_band_shrink_rate_ratio_max=0.18,
        tail_unified_target_drop_to_threshold_frac=0.19,
        tail_unified_target_peak_lead_us=230.0,
        tail_unified_target_shrink_rate_ratio=0.11,
    )

    assert refined["tail_start_refinement_mode"] == "descriptor_score"
    assert refined["tail_start_capture_index"] == 5
    assert refined["tail_start_delay_from_emergence_us"] == 500
    assert refined["tail_start_drop_to_threshold_frac"] == pytest.approx(0.17, rel=1e-6)
    assert refined["tail_start_shrink_rate_ratio"] == pytest.approx(0.117, rel=1e-6)
    assert refined["tail_start_to_tail_peak_delta_us"] == pytest.approx(223.0, rel=1e-6)
    assert refined["tail_score_candidate_count"] == 3
    assert sum(1 for row in candidate_rows if row["is_selected"]) == 1
    assert next(row for row in candidate_rows if row["is_selected"])["capture_index"] == 5


def test_refine_tail_onset_for_review_scores_shoulder_candidates(monkeypatch):
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=100.0)
        for capture_index in range(1, 8)
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_start_selection_mode": "shoulder_adjusted",
        "preliminary_tail_start_capture_index": 4,
        "preliminary_tail_start_delay_from_emergence_us": 400,
        "preliminary_tail_start_position": 3,
        "tail_shoulder_end_capture_index": 6,
        "tail_shoulder_end_delay_from_emergence_us": 600,
        "tail_shoulder_end_position": 5,
        "tail_confirmation_capture_index": 7,
        "tail_confirmation_delay_from_emergence_us": 700,
        "tail_confirmation_position": 6,
        "tail_start_capture_index": 7,
        "tail_start_delay_from_emergence_us": 700,
        "tail_start_position": 6,
        "tail_onset_status": "ok",
        "tail_width_threshold_px": 80.0,
    }

    monkeypatch.setattr(
        mod,
        "_tail_descriptor_context",
        lambda *_args, **_kwargs: {
            "tail_peak_shrink_rate_norm_per_ms": 1.0,
            "tail_peak_shrink_rate_delay_us": 844.0,
        },
    )

    descriptor_by_position = {
        3: {
            "candidate_window_kind": "shoulder_adjusted",
            "position": 3,
            "capture_index": 4,
            "delay_from_emergence_us": 400.0,
            "width_px": 96.0,
            "drop_frac": 0.04,
            "drop_to_threshold_frac": 0.20,
            "shrink_rate_norm_per_ms": 0.05,
            "shrink_rate_ratio": 0.05,
            "tail_peak_lead_us": 444.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        4: {
            "candidate_window_kind": "shoulder_adjusted",
            "position": 4,
            "capture_index": 5,
            "delay_from_emergence_us": 500.0,
            "width_px": 96.1,
            "drop_frac": 0.039,
            "drop_to_threshold_frac": 0.195,
            "shrink_rate_norm_per_ms": 0.107,
            "shrink_rate_ratio": 0.107,
            "tail_peak_lead_us": 244.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        5: {
            "candidate_window_kind": "shoulder_adjusted",
            "position": 5,
            "capture_index": 6,
            "delay_from_emergence_us": 600.0,
            "width_px": 90.0,
            "drop_frac": 0.10,
            "drop_to_threshold_frac": 0.50,
            "shrink_rate_norm_per_ms": 0.35,
            "shrink_rate_ratio": 0.35,
            "tail_peak_lead_us": 144.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        6: {
            "candidate_window_kind": "shoulder_adjusted",
            "position": 6,
            "capture_index": 7,
            "delay_from_emergence_us": 700.0,
            "width_px": 88.0,
            "drop_frac": 0.12,
            "drop_to_threshold_frac": 0.60,
            "shrink_rate_norm_per_ms": 0.40,
            "shrink_rate_ratio": 0.40,
            "tail_peak_lead_us": 144.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": True,
        },
    }
    monkeypatch.setattr(
        mod,
        "_tail_candidate_descriptor_row",
        lambda _feature_rows, position, **_kwargs: dict(descriptor_by_position[int(position)]),
    )

    refined, candidate_rows = mod._refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=3,
        tail_start_mode=mod.TAIL_START_MODE_DESCRIPTOR_SCORE,
        tail_direct_target_drop_to_threshold_frac=0.171,
        tail_direct_target_peak_lead_us=223.0,
        tail_direct_target_shrink_rate_ratio=0.117,
        tail_shoulder_target_drop_to_threshold_frac=0.195,
        tail_shoulder_target_peak_lead_us=244.0,
        tail_shoulder_target_shrink_rate_ratio=0.107,
        tail_score_drop_weight=3.0,
        tail_score_peak_lead_weight=1.5,
        tail_score_shrink_rate_weight=1.0,
        tail_score_drop_scale=0.08,
        tail_score_peak_lead_scale_us=60.0,
        tail_score_shrink_rate_scale=0.04,
        tail_unified_band_drop_min=0.15,
        tail_unified_band_drop_max=0.35,
        tail_unified_band_peak_lead_min_us=180.0,
        tail_unified_band_peak_lead_max_us=320.0,
        tail_unified_band_shrink_rate_ratio_min=0.05,
        tail_unified_band_shrink_rate_ratio_max=0.18,
        tail_unified_target_drop_to_threshold_frac=0.19,
        tail_unified_target_peak_lead_us=230.0,
        tail_unified_target_shrink_rate_ratio=0.11,
    )

    assert refined["tail_start_refinement_mode"] == "descriptor_score"
    assert refined["tail_start_capture_index"] == 5
    assert refined["tail_start_delay_from_emergence_us"] == 500
    assert refined["tail_start_drop_to_threshold_frac"] == pytest.approx(0.195, rel=1e-6)
    assert refined["tail_start_shrink_rate_ratio"] == pytest.approx(0.107, rel=1e-6)
    assert refined["tail_start_to_tail_peak_delta_us"] == pytest.approx(244.0, rel=1e-6)
    assert sum(1 for row in candidate_rows if row["is_selected"]) == 1
    assert next(row for row in candidate_rows if row["is_selected"])["capture_index"] == 5


def test_refine_tail_onset_for_review_falls_back_when_candidate_descriptors_missing(monkeypatch):
    feature_rows = [
        _feature_row(capture_index, delay_from_emergence_us=capture_index * 100, volume_nl=float(capture_index), width_px=100.0)
        for capture_index in range(1, 7)
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_start_selection_mode": "direct_backtrack",
        "direct_final_tail_start_capture_index": 4,
        "direct_final_tail_start_delay_from_emergence_us": 400,
        "direct_final_tail_start_position": 3,
        "tail_confirmation_capture_index": 6,
        "tail_confirmation_delay_from_emergence_us": 600,
        "tail_confirmation_position": 5,
        "tail_start_capture_index": 4,
        "tail_start_delay_from_emergence_us": 400,
        "tail_start_position": 3,
        "tail_onset_status": "ok",
        "tail_width_threshold_px": 80.0,
    }

    monkeypatch.setattr(
        mod,
        "_tail_descriptor_context",
        lambda *_args, **_kwargs: {
            "tail_peak_shrink_rate_norm_per_ms": None,
            "tail_peak_shrink_rate_delay_us": None,
        },
    )
    monkeypatch.setattr(
        mod,
        "_tail_candidate_descriptor_row",
        lambda _feature_rows, position, **_kwargs: {
            "candidate_window_kind": "direct_backtrack",
            "position": int(position),
            "capture_index": int(position) + 1,
            "delay_from_emergence_us": float((int(position) + 1) * 100),
            "width_px": 100.0,
            "drop_frac": None,
            "drop_to_threshold_frac": None,
            "shrink_rate_norm_per_ms": None,
            "shrink_rate_ratio": None,
            "tail_peak_lead_us": None,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "is_selected": False,
            "is_legacy_anchor": int(position) == 3,
        },
    )

    refined, candidate_rows = mod._refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=3,
        tail_start_mode=mod.TAIL_START_MODE_DESCRIPTOR_SCORE,
        tail_direct_target_drop_to_threshold_frac=0.171,
        tail_direct_target_peak_lead_us=223.0,
        tail_direct_target_shrink_rate_ratio=0.117,
        tail_shoulder_target_drop_to_threshold_frac=0.195,
        tail_shoulder_target_peak_lead_us=244.0,
        tail_shoulder_target_shrink_rate_ratio=0.107,
        tail_score_drop_weight=3.0,
        tail_score_peak_lead_weight=1.5,
        tail_score_shrink_rate_weight=1.0,
        tail_score_drop_scale=0.08,
        tail_score_peak_lead_scale_us=60.0,
        tail_score_shrink_rate_scale=0.04,
        tail_unified_band_drop_min=0.15,
        tail_unified_band_drop_max=0.35,
        tail_unified_band_peak_lead_min_us=180.0,
        tail_unified_band_peak_lead_max_us=320.0,
        tail_unified_band_shrink_rate_ratio_min=0.05,
        tail_unified_band_shrink_rate_ratio_max=0.18,
        tail_unified_target_drop_to_threshold_frac=0.19,
        tail_unified_target_peak_lead_us=230.0,
        tail_unified_target_shrink_rate_ratio=0.11,
    )

    assert refined["tail_start_refinement_mode"] == "legacy"
    assert refined["tail_start_capture_index"] == 4
    assert refined["tail_start_delay_from_emergence_us"] == 400
    assert refined["tail_start_score"] is None
    assert refined["tail_score_candidate_count"] == 3
    assert sum(1 for row in candidate_rows if row["is_selected"]) == 1
    assert next(row for row in candidate_rows if row["is_selected"])["capture_index"] == 4


def test_refine_tail_onset_for_review_descriptor_unified_uses_preliminary_window_for_direct(
    monkeypatch,
):
    feature_rows = [
        _feature_row(
            capture_index,
            delay_from_emergence_us=capture_index * 100,
            volume_nl=float(capture_index),
            width_px=100.0,
        )
        for capture_index in range(1, 8)
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_start_selection_mode": "direct_backtrack",
        "preliminary_tail_start_capture_index": 3,
        "preliminary_tail_start_delay_from_emergence_us": 300,
        "preliminary_tail_start_position": 2,
        "direct_final_tail_start_capture_index": 4,
        "direct_final_tail_start_delay_from_emergence_us": 400,
        "direct_final_tail_start_position": 3,
        "tail_confirmation_capture_index": 6,
        "tail_confirmation_delay_from_emergence_us": 600,
        "tail_confirmation_position": 5,
        "tail_start_capture_index": 4,
        "tail_start_delay_from_emergence_us": 400,
        "tail_start_position": 3,
        "tail_onset_status": "ok",
        "tail_width_threshold_px": 80.0,
    }

    monkeypatch.setattr(
        mod,
        "_tail_descriptor_context",
        lambda *_args, **_kwargs: {
            "tail_peak_shrink_rate_norm_per_ms": 1.0,
            "tail_peak_shrink_rate_delay_us": 520.0,
        },
    )
    descriptor_by_position = {
        2: {
            "candidate_window_kind": "descriptor_unified",
            "position": 2,
            "capture_index": 3,
            "delay_from_emergence_us": 300.0,
            "width_px": 97.0,
            "drop_frac": 0.03,
            "drop_to_threshold_frac": 0.15,
            "shrink_rate_norm_per_ms": 0.07,
            "shrink_rate_ratio": 0.07,
            "tail_peak_lead_us": 220.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        3: {
            "candidate_window_kind": "descriptor_unified",
            "position": 3,
            "capture_index": 4,
            "delay_from_emergence_us": 400.0,
            "width_px": 95.0,
            "drop_frac": 0.05,
            "drop_to_threshold_frac": 0.25,
            "shrink_rate_norm_per_ms": 0.12,
            "shrink_rate_ratio": 0.12,
            "tail_peak_lead_us": 120.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": True,
        },
        4: {
            "candidate_window_kind": "descriptor_unified",
            "position": 4,
            "capture_index": 5,
            "delay_from_emergence_us": 500.0,
            "width_px": 90.0,
            "drop_frac": 0.10,
            "drop_to_threshold_frac": 0.50,
            "shrink_rate_norm_per_ms": 0.30,
            "shrink_rate_ratio": 0.30,
            "tail_peak_lead_us": 20.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        5: {
            "candidate_window_kind": "descriptor_unified",
            "position": 5,
            "capture_index": 6,
            "delay_from_emergence_us": 600.0,
            "width_px": 84.0,
            "drop_frac": 0.16,
            "drop_to_threshold_frac": 0.80,
            "shrink_rate_norm_per_ms": 0.60,
            "shrink_rate_ratio": 0.60,
            "tail_peak_lead_us": -80.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
    }
    monkeypatch.setattr(
        mod,
        "_tail_candidate_descriptor_row",
        lambda _feature_rows, position, **_kwargs: dict(descriptor_by_position[int(position)]),
    )

    refined, candidate_rows = mod._refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=2,
        tail_start_mode=mod.TAIL_START_MODE_DESCRIPTOR_UNIFIED,
        tail_direct_target_drop_to_threshold_frac=0.171,
        tail_direct_target_peak_lead_us=223.0,
        tail_direct_target_shrink_rate_ratio=0.117,
        tail_shoulder_target_drop_to_threshold_frac=0.195,
        tail_shoulder_target_peak_lead_us=244.0,
        tail_shoulder_target_shrink_rate_ratio=0.107,
        tail_score_drop_weight=3.0,
        tail_score_peak_lead_weight=1.5,
        tail_score_shrink_rate_weight=1.0,
        tail_score_drop_scale=0.08,
        tail_score_peak_lead_scale_us=60.0,
        tail_score_shrink_rate_scale=0.04,
        tail_unified_band_drop_min=0.15,
        tail_unified_band_drop_max=0.35,
        tail_unified_band_peak_lead_min_us=180.0,
        tail_unified_band_peak_lead_max_us=320.0,
        tail_unified_band_shrink_rate_ratio_min=0.05,
        tail_unified_band_shrink_rate_ratio_max=0.18,
        tail_unified_target_drop_to_threshold_frac=0.19,
        tail_unified_target_peak_lead_us=230.0,
        tail_unified_target_shrink_rate_ratio=0.11,
    )

    assert refined["tail_start_refinement_mode"] == "descriptor_unified"
    assert refined["tail_start_band_selection_status"] == "earliest_in_band"
    assert refined["tail_in_band_candidate_count"] == 1
    assert refined["tail_start_capture_index"] == 3
    assert refined["tail_score_window_start_capture_index"] == 3
    assert refined["tail_score_window_end_capture_index"] == 6
    selected_row = next(row for row in candidate_rows if row["is_selected"])
    assert selected_row["capture_index"] == 3
    assert selected_row["selection_reason"] == "earliest_in_band"
    assert selected_row["within_unified_band"] is True


def test_refine_tail_onset_for_review_descriptor_unified_uses_confirmation_window_for_shoulder(
    monkeypatch,
):
    feature_rows = [
        _feature_row(
            capture_index,
            delay_from_emergence_us=capture_index * 100,
            volume_nl=float(capture_index),
            width_px=100.0,
        )
        for capture_index in range(1, 9)
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_start_selection_mode": "shoulder_adjusted",
        "preliminary_tail_start_capture_index": 4,
        "preliminary_tail_start_delay_from_emergence_us": 400,
        "preliminary_tail_start_position": 3,
        "tail_shoulder_end_capture_index": 5,
        "tail_shoulder_end_delay_from_emergence_us": 500,
        "tail_shoulder_end_position": 4,
        "tail_confirmation_capture_index": 7,
        "tail_confirmation_delay_from_emergence_us": 700,
        "tail_confirmation_position": 6,
        "tail_start_capture_index": 6,
        "tail_start_delay_from_emergence_us": 600,
        "tail_start_position": 5,
        "tail_onset_status": "ok",
        "tail_width_threshold_px": 80.0,
    }

    monkeypatch.setattr(
        mod,
        "_tail_descriptor_context",
        lambda *_args, **_kwargs: {
            "tail_peak_shrink_rate_norm_per_ms": 1.0,
            "tail_peak_shrink_rate_delay_us": 720.0,
        },
    )
    descriptor_by_position = {
        3: {
            "candidate_window_kind": "descriptor_unified",
            "position": 3,
            "capture_index": 4,
            "delay_from_emergence_us": 400.0,
            "width_px": 97.0,
            "drop_frac": 0.03,
            "drop_to_threshold_frac": 0.18,
            "shrink_rate_norm_per_ms": 0.08,
            "shrink_rate_ratio": 0.08,
            "tail_peak_lead_us": 320.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        4: {
            "candidate_window_kind": "descriptor_unified",
            "position": 4,
            "capture_index": 5,
            "delay_from_emergence_us": 500.0,
            "width_px": 96.0,
            "drop_frac": 0.04,
            "drop_to_threshold_frac": 0.22,
            "shrink_rate_norm_per_ms": 0.11,
            "shrink_rate_ratio": 0.11,
            "tail_peak_lead_us": 220.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        5: {
            "candidate_window_kind": "descriptor_unified",
            "position": 5,
            "capture_index": 6,
            "delay_from_emergence_us": 600.0,
            "width_px": 94.0,
            "drop_frac": 0.06,
            "drop_to_threshold_frac": 0.30,
            "shrink_rate_norm_per_ms": 0.14,
            "shrink_rate_ratio": 0.14,
            "tail_peak_lead_us": 120.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": True,
        },
        6: {
            "candidate_window_kind": "descriptor_unified",
            "position": 6,
            "capture_index": 7,
            "delay_from_emergence_us": 700.0,
            "width_px": 88.0,
            "drop_frac": 0.12,
            "drop_to_threshold_frac": 0.60,
            "shrink_rate_norm_per_ms": 0.40,
            "shrink_rate_ratio": 0.40,
            "tail_peak_lead_us": 20.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
    }
    monkeypatch.setattr(
        mod,
        "_tail_candidate_descriptor_row",
        lambda _feature_rows, position, **_kwargs: dict(descriptor_by_position[int(position)]),
    )

    refined, candidate_rows = mod._refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=3,
        tail_start_mode=mod.TAIL_START_MODE_DESCRIPTOR_UNIFIED,
        tail_direct_target_drop_to_threshold_frac=0.171,
        tail_direct_target_peak_lead_us=223.0,
        tail_direct_target_shrink_rate_ratio=0.117,
        tail_shoulder_target_drop_to_threshold_frac=0.195,
        tail_shoulder_target_peak_lead_us=244.0,
        tail_shoulder_target_shrink_rate_ratio=0.107,
        tail_score_drop_weight=3.0,
        tail_score_peak_lead_weight=1.5,
        tail_score_shrink_rate_weight=1.0,
        tail_score_drop_scale=0.08,
        tail_score_peak_lead_scale_us=60.0,
        tail_score_shrink_rate_scale=0.04,
        tail_unified_band_drop_min=0.15,
        tail_unified_band_drop_max=0.35,
        tail_unified_band_peak_lead_min_us=180.0,
        tail_unified_band_peak_lead_max_us=320.0,
        tail_unified_band_shrink_rate_ratio_min=0.05,
        tail_unified_band_shrink_rate_ratio_max=0.18,
        tail_unified_target_drop_to_threshold_frac=0.19,
        tail_unified_target_peak_lead_us=230.0,
        tail_unified_target_shrink_rate_ratio=0.11,
    )

    assert refined["tail_start_refinement_mode"] == "descriptor_unified"
    assert refined["tail_start_capture_index"] == 4
    assert refined["tail_start_band_selection_status"] == "earliest_in_band"
    assert refined["tail_score_window_start_capture_index"] == 4
    assert refined["tail_score_window_end_capture_index"] == 7
    assert [row["capture_index"] for row in candidate_rows] == [4, 5, 6, 7]


def test_refine_tail_onset_for_review_descriptor_unified_falls_back_to_best_score(
    monkeypatch,
):
    feature_rows = [
        _feature_row(
            capture_index,
            delay_from_emergence_us=capture_index * 100,
            volume_nl=float(capture_index),
            width_px=100.0,
        )
        for capture_index in range(1, 7)
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_start_selection_mode": "direct_backtrack",
        "preliminary_tail_start_capture_index": 4,
        "preliminary_tail_start_delay_from_emergence_us": 400,
        "preliminary_tail_start_position": 3,
        "direct_final_tail_start_capture_index": 4,
        "direct_final_tail_start_delay_from_emergence_us": 400,
        "direct_final_tail_start_position": 3,
        "tail_confirmation_capture_index": 6,
        "tail_confirmation_delay_from_emergence_us": 600,
        "tail_confirmation_position": 5,
        "tail_start_capture_index": 4,
        "tail_start_delay_from_emergence_us": 400,
        "tail_start_position": 3,
        "tail_onset_status": "ok",
        "tail_width_threshold_px": 80.0,
    }

    monkeypatch.setattr(
        mod,
        "_tail_descriptor_context",
        lambda *_args, **_kwargs: {
            "tail_peak_shrink_rate_norm_per_ms": 1.0,
            "tail_peak_shrink_rate_delay_us": 950.0,
        },
    )
    descriptor_by_position = {
        3: {
            "candidate_window_kind": "descriptor_unified",
            "position": 3,
            "capture_index": 4,
            "delay_from_emergence_us": 400.0,
            "width_px": 97.0,
            "drop_frac": 0.03,
            "drop_to_threshold_frac": 0.10,
            "shrink_rate_norm_per_ms": 0.02,
            "shrink_rate_ratio": 0.02,
            "tail_peak_lead_us": 550.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": True,
        },
        4: {
            "candidate_window_kind": "descriptor_unified",
            "position": 4,
            "capture_index": 5,
            "delay_from_emergence_us": 500.0,
            "width_px": 95.0,
            "drop_frac": 0.05,
            "drop_to_threshold_frac": 0.40,
            "shrink_rate_norm_per_ms": 0.18,
            "shrink_rate_ratio": 0.18,
            "tail_peak_lead_us": 450.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
        5: {
            "candidate_window_kind": "descriptor_unified",
            "position": 5,
            "capture_index": 6,
            "delay_from_emergence_us": 600.0,
            "width_px": 94.0,
            "drop_frac": 0.06,
            "drop_to_threshold_frac": 0.38,
            "shrink_rate_norm_per_ms": 0.22,
            "shrink_rate_ratio": 0.22,
            "tail_peak_lead_us": 350.0,
            "score_drop_term": None,
            "score_peak_lead_term": None,
            "score_shrink_rate_term": None,
            "score_total": None,
            "within_drop_band": None,
            "within_peak_lead_band": None,
            "within_shrink_rate_band": None,
            "within_unified_band": None,
            "selection_reason": None,
            "is_selected": False,
            "is_legacy_anchor": False,
        },
    }
    monkeypatch.setattr(
        mod,
        "_tail_candidate_descriptor_row",
        lambda _feature_rows, position, **_kwargs: dict(descriptor_by_position[int(position)]),
    )

    refined, candidate_rows = mod._refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=3,
        tail_start_mode=mod.TAIL_START_MODE_DESCRIPTOR_UNIFIED,
        tail_direct_target_drop_to_threshold_frac=0.171,
        tail_direct_target_peak_lead_us=223.0,
        tail_direct_target_shrink_rate_ratio=0.117,
        tail_shoulder_target_drop_to_threshold_frac=0.195,
        tail_shoulder_target_peak_lead_us=244.0,
        tail_shoulder_target_shrink_rate_ratio=0.107,
        tail_score_drop_weight=3.0,
        tail_score_peak_lead_weight=1.5,
        tail_score_shrink_rate_weight=1.0,
        tail_score_drop_scale=0.08,
        tail_score_peak_lead_scale_us=60.0,
        tail_score_shrink_rate_scale=0.04,
        tail_unified_band_drop_min=0.15,
        tail_unified_band_drop_max=0.35,
        tail_unified_band_peak_lead_min_us=180.0,
        tail_unified_band_peak_lead_max_us=320.0,
        tail_unified_band_shrink_rate_ratio_min=0.05,
        tail_unified_band_shrink_rate_ratio_max=0.18,
        tail_unified_target_drop_to_threshold_frac=0.19,
        tail_unified_target_peak_lead_us=230.0,
        tail_unified_target_shrink_rate_ratio=0.11,
    )

    assert refined["tail_start_refinement_mode"] == "descriptor_unified"
    assert refined["tail_start_band_selection_status"] == "best_score_fallback"
    assert refined["tail_in_band_candidate_count"] == 0
    assert refined["tail_start_capture_index"] == 6
    assert next(row for row in candidate_rows if row["is_selected"])["selection_reason"] == (
        "best_score_fallback"
    )


def test_refine_tail_onset_for_review_descriptor_unified_falls_back_when_window_missing(
    monkeypatch,
):
    feature_rows = [
        _feature_row(
            capture_index,
            delay_from_emergence_us=capture_index * 100,
            volume_nl=float(capture_index),
            width_px=100.0,
        )
        for capture_index in range(1, 6)
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_end_capture_index": 3,
        "steady_width_plateau_px": 100.0,
    }
    tail_onset = {
        "tail_start_selection_mode": "direct_backtrack",
        "preliminary_tail_start_capture_index": None,
        "preliminary_tail_start_position": None,
        "direct_final_tail_start_capture_index": None,
        "direct_final_tail_start_position": None,
        "tail_confirmation_capture_index": 5,
        "tail_confirmation_position": 4,
        "tail_start_capture_index": 4,
        "tail_start_delay_from_emergence_us": 400,
        "tail_start_position": 3,
        "tail_onset_status": "ok",
        "tail_width_threshold_px": 80.0,
    }

    monkeypatch.setattr(
        mod,
        "_tail_descriptor_context",
        lambda *_args, **_kwargs: {
            "tail_peak_shrink_rate_norm_per_ms": 1.0,
            "tail_peak_shrink_rate_delay_us": 700.0,
        },
    )

    refined, candidate_rows = mod._refine_tail_onset_for_review(
        feature_rows,
        steady_fit,
        tail_onset,
        first_untrusted_capture_index=3,
        tail_start_mode=mod.TAIL_START_MODE_DESCRIPTOR_UNIFIED,
        tail_direct_target_drop_to_threshold_frac=0.171,
        tail_direct_target_peak_lead_us=223.0,
        tail_direct_target_shrink_rate_ratio=0.117,
        tail_shoulder_target_drop_to_threshold_frac=0.195,
        tail_shoulder_target_peak_lead_us=244.0,
        tail_shoulder_target_shrink_rate_ratio=0.107,
        tail_score_drop_weight=3.0,
        tail_score_peak_lead_weight=1.5,
        tail_score_shrink_rate_weight=1.0,
        tail_score_drop_scale=0.08,
        tail_score_peak_lead_scale_us=60.0,
        tail_score_shrink_rate_scale=0.04,
        tail_unified_band_drop_min=0.15,
        tail_unified_band_drop_max=0.35,
        tail_unified_band_peak_lead_min_us=180.0,
        tail_unified_band_peak_lead_max_us=320.0,
        tail_unified_band_shrink_rate_ratio_min=0.05,
        tail_unified_band_shrink_rate_ratio_max=0.18,
        tail_unified_target_drop_to_threshold_frac=0.19,
        tail_unified_target_peak_lead_us=230.0,
        tail_unified_target_shrink_rate_ratio=0.11,
    )

    assert refined["tail_start_refinement_mode"] == "legacy"
    assert refined["tail_start_band_selection_status"] == "legacy_fallback_missing_window"
    assert refined["tail_start_capture_index"] == 4
    assert candidate_rows == []


def test_middle_extrapolation_is_unresolved_without_tail_onset():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=74.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=74.0),
        {
            **_feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=74.0),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_rate_nl_per_us": 0.01,
        "steady_intercept_nl": 0.0,
    }
    tail_onset = {"tail_start_capture_index": None}
    fov_report = {"first_untrusted_capture_index": 5}

    middle = mod._middle_extrapolation(feature_rows, steady_fit, tail_onset, fov_report)

    assert middle["trusted_visible_volume_nl"] == 4.0
    assert middle["middle_extrapolated_volume_nl"] is None
    assert middle["middle_extrapolation_status"] == "unresolved_no_tail_onset"
    assert middle["partial_total_without_tail_nl"] == 4.0


def test_middle_extrapolation_is_zero_when_tail_starts_before_first_untrusted():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=74.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=68.0),
        {
            **_feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=66.0),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_rate_nl_per_us": 0.01,
        "steady_intercept_nl": 0.0,
    }
    tail_onset = {"tail_start_capture_index": 4}
    fov_report = {"first_untrusted_capture_index": 5}

    middle = mod._middle_extrapolation(feature_rows, steady_fit, tail_onset, fov_report)

    assert middle["middle_extrapolated_volume_nl"] == 0.0
    assert middle["middle_extrapolation_status"] == "zero_tail_before_fov_exit"
    assert middle["partial_total_without_tail_nl"] == 4.0


def test_middle_extrapolation_uses_backtracked_tail_start_not_confirmation_frame():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=79.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=77.0),
        {
            **_feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=74.0),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=62.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=50.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_rate_nl_per_us": 0.01,
        "steady_intercept_nl": 0.0,
    }
    tail_onset = {
        "tail_start_capture_index": 3,
        "tail_confirmation_capture_index": 6,
    }
    fov_report = {"first_untrusted_capture_index": 5}

    middle = mod._middle_extrapolation(feature_rows, steady_fit, tail_onset, fov_report)

    assert middle["middle_extrapolated_volume_nl"] == 0.0
    assert middle["middle_extrapolation_status"] == "zero_tail_before_fov_exit"


def test_middle_extrapolation_uses_shoulder_adjusted_tail_start():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=74.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=74.0),
        {
            **_feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=74.0),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=73.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=73.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=73.0),
        _feature_row(9, delay_from_emergence_us=900, volume_nl=9.0, width_px=73.0),
        _feature_row(10, delay_from_emergence_us=1000, volume_nl=10.0, width_px=73.0),
        _feature_row(11, delay_from_emergence_us=1100, volume_nl=11.0, width_px=72.0),
        _feature_row(12, delay_from_emergence_us=1200, volume_nl=12.0, width_px=70.0),
        _feature_row(13, delay_from_emergence_us=1300, volume_nl=13.0, width_px=68.0),
        _feature_row(14, delay_from_emergence_us=1400, volume_nl=14.0, width_px=64.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_rate_nl_per_us": 0.01,
        "steady_intercept_nl": 0.0,
        "steady_end_capture_index": 4,
        "steady_width_plateau_px": 74.0,
    }
    tail_onset = mod._find_tail_onset(
        feature_rows,
        steady_fit,
        first_untrusted_capture_index=5,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )
    fov_report = {"first_untrusted_capture_index": 5}

    middle = mod._middle_extrapolation(feature_rows, steady_fit, tail_onset, fov_report)

    assert tail_onset["tail_start_capture_index"] == 12
    assert middle["middle_extrapolated_volume_nl"] == pytest.approx(7.0, rel=1e-6)


def test_middle_extrapolation_is_zero_when_no_fov_exit_occurs():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=74.0),
    ]
    steady_fit = {
        "steady_fit_status": "ok",
        "steady_rate_nl_per_us": 0.01,
        "steady_intercept_nl": 0.0,
    }
    tail_onset = {"tail_start_capture_index": None}
    fov_report = {"first_untrusted_capture_index": None}

    middle = mod._middle_extrapolation(feature_rows, steady_fit, tail_onset, fov_report)

    assert middle["middle_extrapolated_volume_nl"] == 0.0
    assert middle["middle_extrapolation_status"] == "not_needed_no_fov_exit"
    assert middle["partial_total_without_tail_nl"] == 3.0


def test_propagated_volume_uncertainty_from_review_is_reproducible_for_in_band_candidates():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
        {
            **_feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=73.0),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=71.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=68.0),
    ]
    steady_fit = {
        "steady_rate_ci95_low_nl_per_us": 0.01,
        "steady_rate_ci95_high_nl_per_us": 0.02,
    }
    middle = {
        "trusted_visible_volume_nl": 3.0,
        "partial_total_without_tail_nl": 6.0,
    }
    candidate_rows = [
        {
            "capture_index": 4,
            "delay_from_emergence_us": 400.0,
            "within_unified_band": True,
            "score_total": 1.5,
        },
        {
            "capture_index": 5,
            "delay_from_emergence_us": 500.0,
            "within_unified_band": True,
            "score_total": 1.0,
        },
    ]

    result_a = mod._propagated_volume_uncertainty_from_review(
        feature_rows,
        steady_fit,
        middle,
        {"first_untrusted_capture_index": 3},
        tail_start_candidate_rows=candidate_rows,
        first_untrusted_delay_from_emergence_us=300,
        sample_count=512,
        seed=7,
        tail_uncertainty_score_tolerance=1.0,
    )
    result_b = mod._propagated_volume_uncertainty_from_review(
        feature_rows,
        steady_fit,
        middle,
        {"first_untrusted_capture_index": 3},
        tail_start_candidate_rows=candidate_rows,
        first_untrusted_delay_from_emergence_us=300,
        sample_count=512,
        seed=7,
        tail_uncertainty_score_tolerance=1.0,
    )

    assert result_a == result_b
    assert result_a["tail_start_uncertainty_source"] == "unified_band"
    assert result_a["tail_start_uncertainty_candidate_count"] == 2
    assert result_a["predicted_volume_uncertainty_status"] == "ok"
    assert result_a["volume_uncertainty_sample_count"] == 512
    assert result_a["tail_start_uncertainty_p05_us"] == pytest.approx(400.0, rel=1e-6)
    assert result_a["tail_start_uncertainty_p95_us"] == pytest.approx(500.0, rel=1e-6)
    assert result_a["predicted_volume_uncertainty_p05_nl"] < result_a["predicted_volume_uncertainty_p95_nl"]
    assert result_a["predicted_volume_uncertainty_width_nl"] > 0.0
    assert result_a["predicted_volume_uncertainty_relative_width"] > 0.0


def test_propagated_volume_uncertainty_from_review_uses_score_tolerance_when_no_in_band_candidates():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0),
        {
            **_feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=74.0),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=72.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=68.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=64.0),
    ]
    result = mod._propagated_volume_uncertainty_from_review(
        feature_rows,
        {
            "steady_rate_ci95_low_nl_per_us": 0.01,
            "steady_rate_ci95_high_nl_per_us": 0.01,
        },
        {
            "trusted_visible_volume_nl": 2.0,
            "partial_total_without_tail_nl": 4.5,
        },
        {"first_untrusted_capture_index": 2},
        tail_start_candidate_rows=[
            {
                "capture_index": 3,
                "delay_from_emergence_us": 300.0,
                "within_unified_band": False,
                "score_total": 0.5,
            },
            {
                "capture_index": 4,
                "delay_from_emergence_us": 400.0,
                "within_unified_band": False,
                "score_total": 1.4,
            },
            {
                "capture_index": 5,
                "delay_from_emergence_us": 500.0,
                "within_unified_band": False,
                "score_total": 3.0,
            },
        ],
        first_untrusted_delay_from_emergence_us=200,
        sample_count=128,
        seed=3,
        tail_uncertainty_score_tolerance=1.0,
    )

    assert result["tail_start_uncertainty_source"] == "score_tolerance"
    assert result["tail_start_uncertainty_candidate_count"] == 2
    assert result["predicted_volume_uncertainty_status"] == "ok"


def test_propagated_volume_uncertainty_from_review_is_unresolved_without_rate_interval():
    result = mod._propagated_volume_uncertainty_from_review(
        [_feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=74.0)],
        {},
        {
            "trusted_visible_volume_nl": 1.0,
            "partial_total_without_tail_nl": 1.0,
        },
        {"first_untrusted_capture_index": 1},
        tail_start_candidate_rows=[],
        first_untrusted_delay_from_emergence_us=100,
        sample_count=64,
        seed=0,
        tail_uncertainty_score_tolerance=1.0,
    )

    assert result["predicted_volume_uncertainty_status"] == "unresolved_missing_rate_interval"
    assert result["predicted_volume_uncertainty_p05_nl"] is None
    assert result["tail_start_uncertainty_candidate_count"] == 0


def test_phase_input_rows_strip_derived_columns_and_review_run_uses_frozen_anchors():
    feature_rows = [
        {
            **_feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
            "phase_label": "steady",
            "steady_selected": True,
            "tail_drop_candidate": False,
            "tail_confirmation_frame": False,
            "tail_shoulder_end_frame": False,
            "tail_start_frame": False,
        },
        {
            **_feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
            "phase_label": "steady",
            "steady_selected": True,
            "tail_drop_candidate": False,
            "tail_confirmation_frame": False,
            "tail_shoulder_end_frame": False,
            "tail_start_frame": False,
        },
        {
            **_feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
            "phase_label": "steady",
            "steady_selected": True,
            "tail_drop_candidate": False,
            "tail_confirmation_frame": False,
            "tail_shoulder_end_frame": False,
            "tail_start_frame": False,
        },
        {
            **_feature_row(4, delay_from_emergence_us=400, volume_nl=4.0, width_px=79.0),
            "phase_label": "transition",
            "steady_selected": False,
            "tail_drop_candidate": False,
            "tail_confirmation_frame": False,
            "tail_shoulder_end_frame": False,
            "tail_start_frame": False,
        },
        {
            **_feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=70.0),
            "phase_label": "tail",
            "steady_selected": False,
            "tail_drop_candidate": True,
            "tail_confirmation_frame": True,
            "tail_shoulder_end_frame": False,
            "tail_start_frame": True,
        },
        {
            **_feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=68.0),
            "phase_label": "tail",
            "steady_selected": False,
            "tail_drop_candidate": True,
            "tail_confirmation_frame": False,
            "tail_shoulder_end_frame": False,
            "tail_start_frame": False,
        },
    ]

    phase_input_rows = mod._phase_input_rows_from_feature_rows(feature_rows)

    assert "phase_label" not in phase_input_rows[0]
    assert "steady_selected" not in phase_input_rows[0]
    assert "tail_start_frame" not in phase_input_rows[0]

    stage5_run = mod._build_stage5_review_run(
        "run_a",
        phase_input_rows,
        steady_fit_payload={
            "steady_fit_status": "ok",
            "steady_capture_indices": [1, 2, 3],
            "steady_start_capture_index": 1,
            "steady_end_capture_index": 3,
            "steady_rate_nl_per_us": 0.01,
            "steady_intercept_nl": 0.0,
            "steady_r2": 1.0,
            "steady_nrmse": 0.0,
            "steady_width_plateau_px": 80.0,
            "steady_width_span_px": 0.0,
            "steady_width_tolerance_px": 4.0,
        },
        fov_report={
            "first_untrusted_capture_index": 4,
            "first_fov_exit_delay_from_emergence_us": 400,
            "trigger_components": [],
        },
        trusted_visible_volume_nl=12.5,
        first_untrusted_delay_from_emergence_us=350,
        width_smooth_window=1,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
        tail_start_mode=mod.TAIL_START_MODE_LEGACY,
    )

    assert stage5_run["summary"]["trusted_visible_volume_nl"] == 12.5
    assert stage5_run["steady_fit"]["steady_rate_nl_per_us"] == pytest.approx(0.01)
    assert stage5_run["steady_fit"]["plateau_capture_indices"] == [1, 2, 3]
    assert stage5_run["steady_fit"]["flow_fit_capture_indices"] == [1, 2, 3]
    assert stage5_run["steady_fit"]["steady_fit_point_count"] == 3
    assert stage5_run["steady_fit"]["steady_rate_confidence_status"] == "ok"
    assert stage5_run["steady_fit"]["steady_rate_ci95_low_nl_per_us"] == pytest.approx(0.01, rel=1e-6)
    assert stage5_run["steady_fit"]["steady_rate_ci95_high_nl_per_us"] == pytest.approx(0.01, rel=1e-6)
    assert stage5_run["tail_onset"]["preliminary_tail_start_capture_index"] == 5
    assert stage5_run["tail_onset"]["direct_final_tail_start_capture_index"] == 5
    assert stage5_run["tail_onset"]["tail_start_capture_index"] == 5
    assert stage5_run["summary"]["steady_fit_point_count"] == 3
    assert stage5_run["summary"]["steady_rate_confidence_status"] == "ok"
    assert stage5_run["summary"]["preliminary_tail_start_capture_index"] == 5
    assert stage5_run["summary"]["direct_final_tail_start_capture_index"] == 5
    assert stage5_run["middle_extrapolation"]["middle_extrapolated_volume_nl"] == pytest.approx(
        1.5, rel=1e-6
    )
    assert stage5_run["summary"]["partial_total_without_tail_nl"] == pytest.approx(14.0, rel=1e-6)
    assert stage5_run["summary"]["predicted_volume_uncertainty_status"] == "unresolved_missing_plausible_tail_candidates"
    assert stage5_run["summary"]["volume_uncertainty_sample_count"] == 0


def test_build_stage5_review_run_rejects_invalid_recomputed_flow_fit():
    feature_rows = [
        _feature_row(1, delay_from_emergence_us=100, volume_nl=1.0, width_px=80.0),
        _feature_row(2, delay_from_emergence_us=200, volume_nl=2.0, width_px=80.0),
        _feature_row(3, delay_from_emergence_us=300, volume_nl=3.0, width_px=80.0),
        _feature_row(4, delay_from_emergence_us=400, volume_nl=8.0, width_px=80.0),
        _feature_row(5, delay_from_emergence_us=500, volume_nl=5.0, width_px=80.0),
        _feature_row(6, delay_from_emergence_us=600, volume_nl=6.0, width_px=80.0),
        _feature_row(7, delay_from_emergence_us=700, volume_nl=7.0, width_px=80.0),
        _feature_row(8, delay_from_emergence_us=800, volume_nl=8.0, width_px=80.0),
        {
            **_feature_row(9, delay_from_emergence_us=900, volume_nl=9.0, width_px=79.0),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
    ]
    phase_input_rows = mod._phase_input_rows_from_feature_rows(feature_rows)

    stage5_run = mod._build_stage5_review_run(
        "run_bad_fit",
        phase_input_rows,
        steady_fit_payload={"steady_fit_status": "ok"},
        fov_report={
            "first_untrusted_capture_index": 9,
            "first_fov_exit_delay_from_emergence_us": 900,
            "trigger_components": [],
        },
        trusted_visible_volume_nl=8.0,
        first_untrusted_delay_from_emergence_us=900,
        width_smooth_window=1,
        steady_fit_mode="recompute",
        steady_fit_exclude_last_trusted_frames=0,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
        steady_fit_r2_min=0.9999,
        steady_fit_nrmse_max=0.0001,
    )

    assert stage5_run["steady_fit"]["steady_fit_status"] == "unresolved_quality_thresholds"
    assert stage5_run["steady_fit"]["steady_rate_nl_per_us"] is None
    assert stage5_run["summary"]["steady_fit_status"] == "unresolved_quality_thresholds"
    assert stage5_run["summary"]["steady_rate_confidence_status"] == "unresolved_quality_thresholds"
    assert stage5_run["tail_onset"]["tail_onset_status"] == "unresolved"
    assert stage5_run["tail_onset"]["tail_start_capture_index"] is None
    assert stage5_run["middle_extrapolation"]["middle_extrapolation_status"] == "unresolved_no_steady_fit"
    assert stage5_run["summary"]["predicted_volume_uncertainty_status"] == "unresolved_missing_rate_interval"
    assert stage5_run["tail_start_candidate_rows"] == []


def test_build_stage5_review_run_recovers_rate_by_retrying_without_backfill():
    feature_rows = _backfill_retry_feature_rows(backfill_volume_nl=1.8) + [
        {
            **_feature_row(10, delay_from_emergence_us=1000, volume_nl=9.4, width_px=68.5),
            "volume_trust_label": fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT,
        },
    ]
    phase_input_rows = mod._phase_input_rows_from_feature_rows(feature_rows)

    stage5_run = mod._build_stage5_review_run(
        "run_retry_fit",
        phase_input_rows,
        steady_fit_payload={"steady_fit_status": "ok"},
        fov_report={
            "first_untrusted_capture_index": 10,
            "first_fov_exit_delay_from_emergence_us": 1000,
            "trigger_components": [],
        },
        trusted_visible_volume_nl=9.3,
        first_untrusted_delay_from_emergence_us=1000,
        width_smooth_window=1,
        steady_fit_mode="recompute",
        steady_fit_exclude_last_trusted_frames=0,
        flow_fit_backfill_max_frames=1,
        flow_fit_backfill_width_delta_px=8.0,
        flow_fit_backfill_monotonic_slack_px=0.75,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
        steady_fit_r2_min=0.985,
        steady_fit_nrmse_max=0.03,
    )

    assert stage5_run["steady_fit"]["steady_fit_status"] == "ok"
    assert stage5_run["steady_fit"]["flow_fit_capture_indices"] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert stage5_run["steady_fit"]["flow_fit_backfill_point_count"] == 0
    assert stage5_run["steady_fit"]["steady_rate_nl_per_us"] is not None
    assert stage5_run["steady_fit"]["steady_rate_ci95_low_nl_per_us"] is not None
    assert stage5_run["steady_fit"]["steady_rate_ci95_high_nl_per_us"] is not None
    assert stage5_run["summary"]["steady_fit_status"] == "ok"
    assert stage5_run["summary"]["steady_rate_confidence_status"] == "ok"
    assert stage5_run["tail_onset"]["tail_onset_status"] == "unresolved"
    assert stage5_run["tail_onset"]["tail_start_capture_index"] is None
    assert stage5_run["middle_extrapolation"]["middle_extrapolation_status"] == "unresolved_no_tail_onset"
    assert stage5_run["summary"]["middle_extrapolation_status"] == "unresolved_no_tail_onset"
    assert stage5_run["summary"]["predicted_volume_uncertainty_status"] == "unresolved_missing_plausible_tail_candidates"
    assert stage5_run["tail_start_candidate_rows"] == []


def test_build_stage5_review_run_accepts_cached_csv_blank_cells():
    phase_input_rows = [
        {
            "run_id": "run_a",
            "capture_id": "cap_000001",
            "capture_index": "1",
            "flash_delay_us": "4700",
            "delay_from_emergence_us": "100",
            "total_visible_volume_nl": "1.0",
            "volume_trust_label": fov_mod.TRUST_LABEL_TRUSTED,
            "attached_near_nozzle_width_median_px": "80.0",
            "attached_near_nozzle_width_iqr_px": "",
            "attached_near_nozzle_band_valid_row_count": "40",
            "attached_near_nozzle_band_y0_px": "124",
            "attached_near_nozzle_band_y1_px": "164",
        },
        {
            "run_id": "run_a",
            "capture_id": "cap_000002",
            "capture_index": "2",
            "flash_delay_us": "4750",
            "delay_from_emergence_us": "200",
            "total_visible_volume_nl": "2.0",
            "volume_trust_label": fov_mod.TRUST_LABEL_TRUSTED,
            "attached_near_nozzle_width_median_px": "79.0",
            "attached_near_nozzle_width_iqr_px": "",
            "attached_near_nozzle_band_valid_row_count": "40",
            "attached_near_nozzle_band_y0_px": "124",
            "attached_near_nozzle_band_y1_px": "164",
        },
    ]

    stage5_run = mod._build_stage5_review_run(
        "run_a",
        phase_input_rows,
        steady_fit_payload={
            "steady_fit_status": "unresolved",
            "steady_capture_indices": [],
            "steady_start_capture_index": None,
            "steady_end_capture_index": None,
            "steady_rate_nl_per_us": None,
            "steady_intercept_nl": None,
            "steady_r2": None,
            "steady_nrmse": None,
            "steady_width_plateau_px": None,
            "steady_width_span_px": None,
            "steady_width_tolerance_px": None,
        },
        fov_report={
            "first_untrusted_capture_index": None,
            "first_fov_exit_delay_from_emergence_us": None,
            "trigger_components": [],
        },
        trusted_visible_volume_nl=2.0,
        first_untrusted_delay_from_emergence_us=None,
        width_smooth_window=3,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )

    assert stage5_run["phase_feature_rows"][0]["attached_near_nozzle_width_iqr_px"] is None
    assert stage5_run["phase_feature_rows"][0]["attached_near_nozzle_width_smoothed_px"] == pytest.approx(
        79.5
    )


def test_export_stage5_fit_writes_expected_outputs(tmp_path, monkeypatch):
    exp_dir, run_dir = _make_silhouette_experiment(tmp_path)
    out_dir = tmp_path / "analysis" / "stream_characterization"

    def _fake_stage4_run(run_id: str, frame_rows: list[dict], **_kwargs):
        frame_metric_rows = []
        edge_rows = []
        for capture_index in range(1, 9):
            trust_label = (
                fov_mod.TRUST_LABEL_TRUSTED
                if capture_index <= 4
                else fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
            )
            frame_metric_rows.append(
                _frame_row(
                    capture_index,
                    delay_from_emergence_us=capture_index * 100,
                    flash_delay_us=4700 + (capture_index * 50),
                    total_visible_volume_nl=float(capture_index),
                    trust_label=trust_label,
                )
            )
            width_px = 74 if capture_index <= 6 else 60
            edge_rows.extend(_edge_rows_for_capture(capture_index, width_px=width_px))
        frame_metric_rows[4]["fov_exit_triggered"] = True
        frame_metric_rows[4]["fov_exit_reason"] = fov_mod.FOV_EXIT_REASON_TRIGGER

        return {
            "run_id": run_id,
            "metric_rows": [],
            "component_rows": [],
            "edge_rows": edge_rows,
            "shift_events": [],
            "frame_metric_rows": frame_metric_rows,
            "fov_report": {
                "schema_version": 1,
                "fov_exit_detected": True,
                "first_fov_exit_capture_index": 5,
                "first_untrusted_capture_index": 5,
                "first_fov_exit_delay_from_emergence_us": 500,
                "trigger_components": [],
            },
            "summary_counts": {
                "frame_count": 8,
                "ok_frame_count": 8,
                "detached_frame_count": 0,
                "component_volume_row_count": 8,
                "trusted_frame_count": 4,
                "untrusted_frame_count": 4,
                "unavailable_geometry_frame_count": 0,
                "total_visible_volume_nl_min": 1.0,
                "total_visible_volume_nl_max": 8.0,
                "detached_visible_volume_nl_max": 0.0,
            },
        }

    monkeypatch.setattr(mod.volume_mod, "_build_stage4_run", _fake_stage4_run)

    payload = mod.export_stage5_fit(
        exp_dir,
        output_root=out_dir,
        min_steady_frames=4,
        width_smooth_window=1,
        tail_persist_frames=2,
        steady_fit_exclude_last_trusted_frames=0,
        tail_start_mode=mod.TAIL_START_MODE_LEGACY,
    )

    assert payload["selected_run_count"] == 1
    run_payload = payload["runs"][0]
    assert run_payload["run_id"] == run_dir.name

    phase_features_csv = Path(run_payload["phase_features_csv"])
    phase_boundaries_json = Path(run_payload["phase_boundaries_json"])
    steady_fit_json = Path(run_payload["steady_fit_json"])
    middle_json = Path(run_payload["middle_extrapolation_json"])
    vt_fit_png = Path(run_payload["vt_fit_png"])
    width_trace_png = Path(run_payload["width_trace_png"])

    assert phase_features_csv.exists()
    assert phase_boundaries_json.exists()
    assert steady_fit_json.exists()
    assert middle_json.exists()
    assert vt_fit_png.exists()
    assert width_trace_png.exists()

    with phase_features_csv.open("r", encoding="utf-8", newline="") as handle:
        feature_rows = list(csv.DictReader(handle))
    middle_payload = json.loads(middle_json.read_text(encoding="utf-8"))
    steady_payload = json.loads(steady_fit_json.read_text(encoding="utf-8"))

    assert len(feature_rows) == 8
    assert "tail_confirmation_frame" in feature_rows[0]
    assert "tail_shoulder_end_frame" in feature_rows[0]
    assert steady_payload["steady_fit_status"] == "ok"
    assert steady_payload["steady_start_capture_index"] == 1
    assert steady_payload["steady_end_capture_index"] == 4
    assert middle_payload["tail_confirmation_capture_index"] == 7
    assert middle_payload["tail_detection_mode"] == "confirmed_persistent"
    assert middle_payload["tail_start_selection_mode"] == "direct_backtrack"
    assert middle_payload["tail_shoulder_end_capture_index"] is None
    assert middle_payload["middle_extrapolation_status"] == "ok"
    assert middle_payload["middle_extrapolated_volume_nl"] == pytest.approx(2.0, rel=1e-6)
    assert middle_payload["partial_total_without_tail_nl"] == pytest.approx(6.0, rel=1e-6)
