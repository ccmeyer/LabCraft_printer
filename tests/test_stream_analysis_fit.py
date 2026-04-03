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
        first_untrusted_capture_index=6,
        tail_drop_frac=0.08,
        tail_persist_frames=2,
    )

    assert tail_onset["tail_onset_status"] == "ok"
    assert tail_onset["tail_start_capture_index"] == 7
    assert tail_onset["tail_start_delay_from_emergence_us"] == 700


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
    assert steady_payload["steady_fit_status"] == "ok"
    assert steady_payload["steady_start_capture_index"] == 1
    assert steady_payload["steady_end_capture_index"] == 4
    assert middle_payload["middle_extrapolation_status"] == "ok"
    assert middle_payload["middle_extrapolated_volume_nl"] == pytest.approx(2.0, rel=1e-6)
    assert middle_payload["partial_total_without_tail_nl"] == pytest.approx(6.0, rel=1e-6)
