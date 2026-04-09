from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from tools.stream_analysis import fov as fov_mod
from tools.stream_analysis import volume as mod
from tests.test_stream_analysis_silhouette import _fake_stage2_run, _make_silhouette_experiment


def _stage3_metric_row(
    capture_index: int,
    *,
    silhouette_status: str = "ok",
    last_valid_y_px: int | None = 470,
    roi_y1: int = 480,
    failure_reason: str | None = None,
    accepted_detached_component_count: int = 0,
):
    return {
        "run_id": "run_a",
        "capture_id": f"cap_{capture_index:06d}",
        "capture_index": capture_index,
        "flash_delay_us": 4750 + ((capture_index - 1) * 50),
        "delay_from_emergence_us": capture_index * 50,
        "silhouette_status": silhouette_status,
        "failure_reason": failure_reason,
        "last_valid_y_px": last_valid_y_px,
        "roi_y1": roi_y1,
        "selected_component_bottom_y_px": last_valid_y_px,
        "selected_component_bbox_h_px": None if last_valid_y_px is None else 40,
        "selected_anchor_center_x_px": 180.0,
        "tracked_nozzle_x_px": 180.0,
        "tracked_nozzle_y_px": 110.0,
        "tracked_confidence": 0.91,
        "accepted_detached_component_count": accepted_detached_component_count,
    }


def _component_metric_row(
    capture_index: int,
    *,
    component_id: str = "attached_primary",
    component_role: str = "attached_primary",
    component_rank: int = 0,
    last_valid_y_px: int | None = 470,
):
    return {
        "run_id": "run_a",
        "capture_id": f"cap_{capture_index:06d}",
        "capture_index": capture_index,
        "flash_delay_us": 4750 + ((capture_index - 1) * 50),
        "component_id": component_id,
        "component_role": component_role,
        "component_rank": component_rank,
        "valid_row_count": 1 if last_valid_y_px is not None else 0,
        "top_y_px": None if last_valid_y_px is None else max(0, int(last_valid_y_px) - 20),
        "bottom_y_px": last_valid_y_px,
        "bbox_x_px": 170,
        "bbox_y_px": None if last_valid_y_px is None else max(0, int(last_valid_y_px) - 20),
        "bbox_w_px": 20,
        "bbox_h_px": 20,
        "last_valid_y_px": last_valid_y_px,
    }


def test_um3_to_nl_converts_expected():
    assert mod._um3_to_nl(1_000_000.0) == 1.0


def test_component_volume_rows_sum_when_components_overlap_in_y():
    component_rows = [
        {
            "run_id": "run_a",
            "capture_id": "cap_001",
            "capture_index": 1,
            "flash_delay_us": 4750,
            "component_id": "attached_primary",
            "component_role": "attached_primary",
            "component_rank": 0,
            "valid_row_count": 2,
            "top_y_px": 100,
            "bottom_y_px": 101,
            "bbox_x_px": 50,
            "bbox_y_px": 100,
            "bbox_w_px": 20,
            "bbox_h_px": 2,
        },
        {
            "run_id": "run_a",
            "capture_id": "cap_001",
            "capture_index": 1,
            "flash_delay_us": 4750,
            "component_id": "detached_01",
            "component_role": "detached_accepted",
            "component_rank": 1,
            "valid_row_count": 2,
            "top_y_px": 100,
            "bottom_y_px": 101,
            "bbox_x_px": 90,
            "bbox_y_px": 100,
            "bbox_w_px": 18,
            "bbox_h_px": 2,
        },
    ]
    edge_rows = [
        {"capture_id": "cap_001", "component_id": "attached_primary", "x_left_px": 50, "x_right_px": 60},
        {"capture_id": "cap_001", "component_id": "attached_primary", "x_left_px": 50, "x_right_px": 60},
        {"capture_id": "cap_001", "component_id": "detached_01", "x_left_px": 92, "x_right_px": 100},
        {"capture_id": "cap_001", "component_id": "detached_01", "x_left_px": 92, "x_right_px": 100},
    ]

    volume_rows = mod._component_volume_rows(component_rows, edge_rows)

    assert len(volume_rows) == 2
    attached_volume = next(row["component_volume_nl"] for row in volume_rows if row["component_id"] == "attached_primary")
    detached_volume = next(row["component_volume_nl"] for row in volume_rows if row["component_id"] == "detached_01")
    assert attached_volume > detached_volume > 0.0
    assert math.isclose(
        attached_volume + detached_volume,
        sum(row["component_volume_nl"] for row in volume_rows),
        rel_tol=1e-9,
    )


def test_frame_metric_rows_keep_plausible_unaccepted_volume_out_of_total_visible_volume():
    stage3_rows = [
        {
            "run_id": "run_a",
            "capture_id": "cap_001",
            "capture_index": 1,
            "flash_delay_us": 4750,
            "delay_from_emergence_us": 50,
            "silhouette_status": "ok",
            "failure_reason": None,
            "accepted_component_count": 2,
            "accepted_detached_component_count": 1,
            "plausible_unaccepted_component_count": 1,
        }
    ]
    component_volume_rows = [
        {
            "run_id": "run_a",
            "capture_id": "cap_001",
            "component_id": "attached_primary",
            "component_role": "attached_primary",
            "component_volume_nl": 10.0,
        },
        {
            "run_id": "run_a",
            "capture_id": "cap_001",
            "component_id": "detached_01",
            "component_role": "detached_accepted",
            "component_volume_nl": 4.0,
        },
        {
            "run_id": "run_a",
            "capture_id": "cap_001",
            "component_id": "plausible_detached_01",
            "component_role": "detached_plausible_unaccepted",
            "component_volume_nl": 3.0,
        },
    ]

    frame_rows = mod._frame_metric_rows(stage3_rows, component_volume_rows)

    assert frame_rows[0]["attached_visible_volume_nl"] == 10.0
    assert frame_rows[0]["detached_visible_volume_nl"] == 4.0
    assert frame_rows[0]["plausible_unaccepted_visible_volume_nl"] == 3.0
    assert frame_rows[0]["total_visible_volume_nl"] == 14.0


def test_fov_labeling_triggers_when_detached_component_is_within_32_px_of_bottom():
    rows = [
        _stage3_metric_row(1, last_valid_y_px=430, accepted_detached_component_count=1),
        _stage3_metric_row(2, last_valid_y_px=430, accepted_detached_component_count=1),
        _stage3_metric_row(3, last_valid_y_px=430, accepted_detached_component_count=1),
    ]
    component_rows = [
        _component_metric_row(1, last_valid_y_px=430),
        _component_metric_row(1, component_id="detached_01", component_role="detached_accepted", component_rank=1, last_valid_y_px=446),
        _component_metric_row(2, last_valid_y_px=430),
        _component_metric_row(2, component_id="detached_01", component_role="detached_accepted", component_rank=1, last_valid_y_px=447),
        _component_metric_row(3, last_valid_y_px=430),
        _component_metric_row(3, component_id="detached_01", component_role="detached_accepted", component_rank=1, last_valid_y_px=447),
    ]

    labeled_rows, report = fov_mod.label_frame_trust(rows, component_rows, near_bottom_px=32)

    assert labeled_rows[0]["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert labeled_rows[0]["accepted_fluid_near_fov_exit"] is False
    assert labeled_rows[1]["volume_trust_label"] == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    assert labeled_rows[1]["accepted_fluid_near_fov_exit"] is True
    assert labeled_rows[1]["fov_near_component_count"] == 1
    assert labeled_rows[1]["min_accepted_fluid_distance_from_bottom_px"] == 32
    assert labeled_rows[1]["fov_exit_triggered"] is True
    assert labeled_rows[2]["volume_trust_label"] == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    assert labeled_rows[2]["fov_exit_triggered"] is False
    assert report["fov_exit_detected"] is True
    assert report["first_fov_exit_capture_index"] == 2
    assert report["trigger_components"] == [
        {
            "component_id": "detached_01",
            "component_rank": 1,
            "component_role": "detached_accepted",
            "distance_from_bottom_px": 32,
            "last_valid_y_px": 447,
        }
    ]


def test_fov_labeling_triggers_when_component_is_exactly_32_px_from_bottom():
    rows = [_stage3_metric_row(1, last_valid_y_px=430)]
    component_rows = [_component_metric_row(1, last_valid_y_px=447)]

    labeled_rows, report = fov_mod.label_frame_trust(rows, component_rows, near_bottom_px=32)

    assert labeled_rows[0]["accepted_fluid_near_fov_exit"] is True
    assert labeled_rows[0]["fov_exit_triggered"] is True
    assert report["fov_exit_detected"] is True


def test_fov_labeling_does_not_trigger_when_component_is_33_px_from_bottom():
    rows = [_stage3_metric_row(1, last_valid_y_px=430)]
    component_rows = [_component_metric_row(1, last_valid_y_px=446)]

    labeled_rows, report = fov_mod.label_frame_trust(rows, component_rows, near_bottom_px=32)

    assert labeled_rows[0]["accepted_fluid_near_fov_exit"] is False
    assert labeled_rows[0]["min_accepted_fluid_distance_from_bottom_px"] == 33
    assert labeled_rows[0]["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert report["fov_exit_detected"] is False


def test_fov_labeling_latches_after_exit_when_geometry_later_unavailable():
    rows = [
        _stage3_metric_row(1, last_valid_y_px=430),
        _stage3_metric_row(2, last_valid_y_px=430, accepted_detached_component_count=1),
        _stage3_metric_row(3, silhouette_status="empty_mask", last_valid_y_px=None, failure_reason="no pixels remain"),
    ]
    component_rows = [
        _component_metric_row(1, last_valid_y_px=430),
        _component_metric_row(2, last_valid_y_px=430),
        _component_metric_row(2, component_id="detached_01", component_role="detached_accepted", component_rank=1, last_valid_y_px=447),
    ]

    labeled_rows, _report = fov_mod.label_frame_trust(rows, component_rows, near_bottom_px=32)

    assert labeled_rows[2]["volume_trust_label"] == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    assert labeled_rows[2]["fov_exit_reason"] == fov_mod.FOV_EXIT_REASON_LATCHED
    assert labeled_rows[2]["volume_is_trusted"] is False


def test_fov_labeling_keeps_pre_exit_failures_as_unavailable_geometry():
    rows = [
        _stage3_metric_row(1, silhouette_status="empty_mask", last_valid_y_px=None, failure_reason="no pixels remain"),
        _stage3_metric_row(2, last_valid_y_px=430),
        _stage3_metric_row(3, last_valid_y_px=430),
    ]
    component_rows = [
        _component_metric_row(2, last_valid_y_px=430),
        _component_metric_row(3, last_valid_y_px=430),
    ]

    labeled_rows, report = fov_mod.label_frame_trust(rows, component_rows, near_bottom_px=32)

    assert labeled_rows[0]["volume_trust_label"] == fov_mod.TRUST_LABEL_UNAVAILABLE_GEOMETRY
    assert labeled_rows[1]["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert labeled_rows[2]["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert report["fov_exit_detected"] is False


def test_fov_labeling_keeps_all_ok_rows_trusted_without_exit():
    rows = [
        _stage3_metric_row(1, last_valid_y_px=430, accepted_detached_component_count=1),
        _stage3_metric_row(2, last_valid_y_px=432),
        _stage3_metric_row(3, last_valid_y_px=433),
    ]
    component_rows = [
        _component_metric_row(1, last_valid_y_px=430),
        _component_metric_row(1, component_id="detached_01", component_role="detached_accepted", component_rank=1, last_valid_y_px=440),
        _component_metric_row(2, last_valid_y_px=432),
        _component_metric_row(3, last_valid_y_px=433),
    ]

    labeled_rows, report = fov_mod.label_frame_trust(rows, component_rows, near_bottom_px=32)

    assert all(row["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED for row in labeled_rows)
    assert report["fov_exit_detected"] is False


def test_export_stage4_volume_sums_attached_and_detached_components_and_uses_nl(tmp_path, monkeypatch):
    exp_dir, _run_dir = _make_silhouette_experiment(
        tmp_path,
        detached_components_by_index={
            2: [
                {
                    "x_offset": -4,
                    "center_y": 330,
                    "radius_x": 18,
                    "radius_y": 24,
                }
            ]
        },
    )
    out_dir = tmp_path / "analysis" / "stream_characterization"
    monkeypatch.setattr(mod.silhouette_mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage4_volume(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    frame_csv = Path(payload["runs"][0]["frame_metrics_csv"])
    component_csv = Path(payload["runs"][0]["component_volumes_csv"])
    timeseries_csv = Path(payload["runs"][0]["volume_timeseries_csv"])

    with frame_csv.open("r", encoding="utf-8", newline="") as handle:
        frame_reader = csv.DictReader(handle)
        frame_rows = list(frame_reader)
        frame_columns = list(frame_reader.fieldnames or [])
    with component_csv.open("r", encoding="utf-8", newline="") as handle:
        component_reader = csv.DictReader(handle)
        component_rows = list(component_reader)
        component_columns = list(component_reader.fieldnames or [])
    with timeseries_csv.open("r", encoding="utf-8", newline="") as handle:
        timeseries_reader = csv.DictReader(handle)
        timeseries_columns = list(timeseries_reader.fieldnames or [])

    frame2 = next(row for row in frame_rows if int(row["capture_index"]) == 2)
    frame2_components = [row for row in component_rows if int(row["capture_index"]) == 2]

    attached = float(frame2["attached_visible_volume_nl"])
    detached = float(frame2["detached_visible_volume_nl"])
    total = float(frame2["total_visible_volume_nl"])

    assert "attached_visible_volume_nl" in frame_columns
    assert "detached_visible_volume_nl" in frame_columns
    assert "total_visible_volume_nl" in frame_columns
    assert "accepted_fluid_near_fov_exit" in frame_columns
    assert "fov_near_component_count" in frame_columns
    assert "min_accepted_fluid_distance_from_bottom_px" in frame_columns
    assert "attached_visible_volume_um3" not in frame_columns
    assert "attached_bottom_touches_fov" not in frame_columns
    assert "component_volume_nl" in component_columns
    assert "component_volume_um3" not in component_columns
    assert "total_visible_volume_um3" not in timeseries_columns
    assert "accepted_fluid_near_fov_exit" in timeseries_columns
    assert "attached_bottom_touches_fov" not in timeseries_columns
    assert frame2["silhouette_status"] == "ok"
    assert frame2["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert int(frame2["accepted_detached_component_count"]) == 1
    assert detached > 0.0
    assert math.isclose(total, attached + detached, rel_tol=1e-9)
    assert {row["component_id"] for row in frame2_components} == {"attached_primary", "detached_01"}


def test_export_stage4_volume_marks_first_near_bottom_frame_as_untrusted_fov_exit(tmp_path, monkeypatch):
    exp_dir, _run_dir = _make_silhouette_experiment(tmp_path, open_bottom_indices={3})
    out_dir = tmp_path / "analysis" / "stream_characterization"
    monkeypatch.setattr(mod.silhouette_mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage4_volume(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    run_info = payload["runs"][0]
    frame_csv = Path(run_info["frame_metrics_csv"])
    report_json = Path(run_info["fov_exit_report_json"])
    vt_png = Path(run_info["vt_png"])

    assert report_json.exists()
    assert vt_png.exists()

    with frame_csv.open("r", encoding="utf-8", newline="") as handle:
        frame_rows = list(csv.DictReader(handle))

    frame1 = next(row for row in frame_rows if int(row["capture_index"]) == 1)
    frame2 = next(row for row in frame_rows if int(row["capture_index"]) == 2)
    frame3 = next(row for row in frame_rows if int(row["capture_index"]) == 3)

    assert frame1["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert frame2["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert frame3["volume_trust_label"] == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    assert frame3["fov_exit_triggered"] == "True"
    assert frame3["accepted_fluid_near_fov_exit"] == "True"
    assert int(frame3["fov_near_component_count"]) >= 1
    assert int(frame3["min_accepted_fluid_distance_from_bottom_px"]) <= 32
    assert frame3["fov_exit_reason"] == fov_mod.FOV_EXIT_REASON_TRIGGER

    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["fov_exit_detected"] is True
    assert report["fov_near_bottom_px"] == 32
    assert report["first_fov_exit_capture_index"] == 3
    assert report["first_untrusted_capture_index"] == 3
    assert len(report["trigger_components"]) >= 1


def test_export_stage4_volume_detached_near_bottom_triggers_exit(tmp_path, monkeypatch):
    exp_dir, _run_dir = _make_silhouette_experiment(
        tmp_path,
        detached_components_by_index={
            2: [
                {
                    "x_offset": -8,
                    "open_bottom": True,
                    "top_y": 332,
                    "wall_half_width": 18,
                    "core_half_width": 9,
                    "cap_height": 16,
                }
            ]
        },
    )
    out_dir = tmp_path / "analysis" / "stream_characterization"
    monkeypatch.setattr(mod.silhouette_mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage4_volume(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    frame_csv = Path(payload["runs"][0]["frame_metrics_csv"])
    report_json = Path(payload["runs"][0]["fov_exit_report_json"])

    with frame_csv.open("r", encoding="utf-8", newline="") as handle:
        frame_rows = list(csv.DictReader(handle))

    frame1 = next(row for row in frame_rows if int(row["capture_index"]) == 1)
    frame2 = next(row for row in frame_rows if int(row["capture_index"]) == 2)

    assert frame1["volume_trust_label"] == fov_mod.TRUST_LABEL_TRUSTED
    assert frame2["volume_trust_label"] == fov_mod.TRUST_LABEL_UNTRUSTED_FOV_EXIT
    assert frame2["accepted_fluid_near_fov_exit"] == "True"
    assert int(frame2["fov_near_component_count"]) >= 1
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert report["fov_exit_detected"] is True
    assert report["first_fov_exit_capture_index"] == 2
    assert any(component["component_id"] == "detached_01" for component in report["trigger_components"])


def test_export_stage4_volume_preserves_stage3_failure_without_attached_primary(tmp_path, monkeypatch):
    exp_dir, _run_dir = _make_silhouette_experiment(tmp_path)
    out_dir = tmp_path / "analysis" / "stream_characterization"

    def _missing_stage2_run(run_id: str, frame_rows: list[dict], **_kwargs):
        tracked_rows = []
        for frame_row in frame_rows:
            tracked_rows.append(
                {
                    "run_id": run_id,
                    "capture_id": frame_row["capture_id"],
                    "capture_index": frame_row["capture_index"],
                    "flash_delay_us": frame_row["flash_delay_us"],
                    "tracked_nozzle_x_px": None,
                    "tracked_nozzle_y_px": None,
                    "tracked_confidence": 0.0,
                    "raw_mode": "no_signal",
                    "final_mode": "no_signal",
                    "segment_id": 0,
                    "shift_event_before": False,
                }
            )
        return {
            "raw_rows": [],
            "tracked_rows": tracked_rows,
            "shift_events": [],
            "frame_diagnostics": [],
        }

    monkeypatch.setattr(mod.silhouette_mod, "_build_stage2_run", _missing_stage2_run)

    payload = mod.export_stage4_volume(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    frame_csv = Path(payload["runs"][0]["frame_metrics_csv"])
    with frame_csv.open("r", encoding="utf-8", newline="") as handle:
        frame_rows = list(csv.DictReader(handle))

    assert all(row["silhouette_status"] == "missing_nozzle_track" for row in frame_rows)
    assert all(row["volume_trust_label"] == fov_mod.TRUST_LABEL_UNAVAILABLE_GEOMETRY for row in frame_rows)
    assert all(row["attached_visible_volume_nl"] == "" for row in frame_rows)
    assert all(row["detached_visible_volume_nl"] == "" for row in frame_rows)
    assert all(row["total_visible_volume_nl"] == "" for row in frame_rows)
