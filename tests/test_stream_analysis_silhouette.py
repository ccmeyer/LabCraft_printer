from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import silhouette as mod
from tests.test_stream_analysis_baseline import _write_jsonl


def _make_stream_frame(
    width: int,
    height: int,
    *,
    x_center: int,
    nozzle_y: int,
    side_blob: bool = False,
    open_bottom: bool = False,
    open_bottom_offset_px: int = 0,
    detached_components=None,
):
    image = np.full((height, width), 245, dtype=np.uint8)
    cv2.rectangle(image, (x_center - 42, 22), (x_center + 42, 68), 95, thickness=-1)
    cv2.rectangle(image, (x_center - 8, 52), (x_center + 8, nozzle_y + 8), 35, thickness=-1)
    cv2.ellipse(image, (x_center, nozzle_y + 72), (28, 70), 0.0, 0.0, 360.0, 35, thickness=-1)
    cv2.rectangle(image, (x_center - 12, nozzle_y + 16), (x_center + 12, nozzle_y + 108), 220, thickness=-1)
    cv2.line(image, (x_center - 16, nozzle_y + 8), (x_center + 16, nozzle_y + 8), 18, thickness=3)
    if open_bottom:
        lower_center = int(x_center + open_bottom_offset_px)
        cv2.rectangle(image, (lower_center - 28, nozzle_y + 24), (lower_center - 16, height - 1), 35, thickness=-1)
        cv2.rectangle(image, (lower_center + 16, nozzle_y + 24), (lower_center + 28, height - 1), 35, thickness=-1)
        cv2.rectangle(image, (lower_center - 28, nozzle_y + 24), (lower_center + 28, nozzle_y + 38), 35, thickness=-1)
        cv2.rectangle(image, (lower_center - 12, nozzle_y + 28), (lower_center + 12, height - 1), 220, thickness=-1)
    for component in detached_components or []:
        component_x = int(x_center + int(component.get("x_offset", 0)))
        if bool(component.get("open_bottom")):
            top_y = int(component.get("top_y", nozzle_y + 170))
            wall_half_width = int(component.get("wall_half_width", 16))
            cap_height = int(component.get("cap_height", 16))
            core_half_width = int(component.get("core_half_width", 10))
            cv2.rectangle(image, (component_x - wall_half_width, top_y), (component_x - (core_half_width + 4), height - 1), 35, thickness=-1)
            cv2.rectangle(image, (component_x + (core_half_width + 4), top_y), (component_x + wall_half_width, height - 1), 35, thickness=-1)
            cv2.rectangle(image, (component_x - wall_half_width, top_y), (component_x + wall_half_width, top_y + cap_height), 35, thickness=-1)
            cv2.rectangle(image, (component_x - core_half_width, top_y + 4), (component_x + core_half_width, height - 1), 220, thickness=-1)
        else:
            center_y = int(component.get("center_y", nozzle_y + 190))
            radius_x = int(component.get("radius_x", 20))
            radius_y = int(component.get("radius_y", 28))
            cv2.ellipse(image, (component_x, center_y), (radius_x, radius_y), 0.0, 0.0, 360.0, 35, thickness=-1)
            if bool(component.get("bright_core", True)):
                inner_radius_x = max(2, int(component.get("inner_radius_x", max(2, radius_x - 7))))
                inner_radius_y = max(2, int(component.get("inner_radius_y", max(2, radius_y - 9))))
                cv2.ellipse(image, (component_x, center_y), (inner_radius_x, inner_radius_y), 0.0, 0.0, 360.0, 220, thickness=-1)
    if side_blob:
        cv2.circle(image, (x_center - 95, nozzle_y + 78), 34, 35, thickness=-1)
    return image


def _make_silhouette_experiment(
    tmp_path: Path,
    *,
    open_bottom_indices=None,
    open_bottom_offsets=None,
    detached_components_by_index=None,
):
    exp_dir = tmp_path / "Stream_characterization-20260327_225650"
    process_root = exp_dir / "calibration_recordings" / dataset_mod.PROCESS_NAME
    run_dir = process_root / "run_20260327_230520_9567e1ee"
    captures_dir = run_dir / "captures"
    captures_dir.mkdir(parents=True, exist_ok=True)
    open_bottom_indices = set(open_bottom_indices or [])
    open_bottom_offsets = dict(open_bottom_offsets or {})
    detached_components_by_index = dict(detached_components_by_index or {})

    run_meta = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "process_name": dataset_mod.PROCESS_NAME,
        "phase_name": "droplet_timecourse",
        "started_at_utc": "2026-03-28T06:05:20.630838Z",
        "ended_at_utc": "2026-03-28T06:05:50.176087Z",
        "outcome": "completed",
        "error_message": "",
    }
    (run_dir / "run_meta.json").write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    events = [
        {
            "event_index": 1,
            "event_type": "stage_changed",
            "payload": {"message": "Timecourse: emergence=4800 us, start=4750 us, step=50 us, window=6000 us (3 frames)"},
        }
    ]
    frames = [
        _make_stream_frame(
            360,
            480,
            x_center=180,
            nozzle_y=110,
            side_blob=False,
            open_bottom=1 in open_bottom_indices,
            open_bottom_offset_px=int(open_bottom_offsets.get(1, 0)),
            detached_components=detached_components_by_index.get(1, []),
        ),
        _make_stream_frame(
            360,
            480,
            x_center=180,
            nozzle_y=110,
            side_blob=True,
            open_bottom=2 in open_bottom_indices,
            open_bottom_offset_px=int(open_bottom_offsets.get(2, 0)),
            detached_components=detached_components_by_index.get(2, []),
        ),
        _make_stream_frame(
            360,
            480,
            x_center=182,
            nozzle_y=112,
            side_blob=False,
            open_bottom=3 in open_bottom_indices,
            open_bottom_offset_px=int(open_bottom_offsets.get(3, 0)),
            detached_components=detached_components_by_index.get(3, []),
        ),
    ]
    for idx, image in enumerate(frames, start=1):
        image_name = f"cap_{idx:06d}_raw_frame.jpg"
        image_relpath = f"captures/{image_name}"
        cv2.imwrite(str(captures_dir / image_name), image)
        flash_delay_us = 4750 + ((idx - 1) * 50)
        events.extend(
            [
                {
                    "event_index": (idx * 3) - 1,
                    "event_type": "stage_changed",
                    "payload": {"message": f"Setting flash_delay = {flash_delay_us} us"},
                },
                {
                    "event_index": idx * 3,
                    "event_type": "capture_saved",
                    "payload": {
                        "capture_id": f"cap_{idx:06d}",
                        "capture_role": "raw_frame",
                        "image_relpath": image_relpath,
                        "metadata": {"stage_text": f"Capturing timecourse frame @ {flash_delay_us} us"},
                    },
                },
                {
                    "event_index": (idx * 3) + 1,
                    "event_type": "capture_result",
                    "payload": {
                        "status": "success",
                        "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        "capture_ref": {
                            "capture_id": f"cap_{idx:06d}",
                            "capture_index": idx,
                            "capture_role": "raw_frame",
                            "image_relpath": image_relpath,
                            "width": 360,
                            "height": 480,
                            "captured_at_utc": f"2026-03-28T06:05:{20 + idx:02d}.000000Z",
                            "stage_text": f"Capturing timecourse frame @ {flash_delay_us} us",
                        },
                    },
                },
            ]
        )

    _write_jsonl(run_dir / "events.jsonl", events)
    _write_jsonl(run_dir / "analysis.jsonl", [{"kind": "calibration_data_updated"}])

    metadata_path = exp_dir / dataset_mod.METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "Dataset name",
                "Print PW",
                "Print Pressure",
                "Refuel PW",
                "Refuel Pressure",
                "Rep",
                "Starting mass",
                "Starting flash",
                "Ending flash",
                "Ending mass",
                "Mass Change",
                "Num printed",
                "Mass/print",
                "CV",
                "Notes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Dataset name": run_dir.name,
                "Print PW": "3000",
                "Print Pressure": "0.65",
                "Refuel PW": "5000",
                "Refuel Pressure": "0.8",
                "Rep": "1",
                "Starting mass": "0",
                "Starting flash": "1987",
                "Ending flash": "2128",
                "Ending mass": "10.03",
                "Mass Change": "10.03",
                "Num printed": "141",
                "Mass/print": "0.0711",
                "CV": "0.99%",
                "Notes": "",
            }
        )
    return exp_dir, run_dir


def _fake_stage2_run(run_id: str, frame_rows: list[dict], **_kwargs):
    tracked_rows = []
    for idx, frame_row in enumerate(frame_rows, start=1):
        tracked_rows.append(
            {
                "run_id": run_id,
                "capture_id": frame_row["capture_id"],
                "capture_index": frame_row["capture_index"],
                "flash_delay_us": frame_row["flash_delay_us"],
                "tracked_nozzle_x_px": 180.0 if idx < 3 else 182.0,
                "tracked_nozzle_y_px": 110.0 if idx < 3 else 112.0,
                "tracked_confidence": 0.92 if idx != 2 else 0.41,
                "raw_mode": "visible_nozzle_line" if idx != 2 else "attached_core_separation",
                "final_mode": "visible_nozzle_line" if idx != 2 else "segment_fill",
                "segment_id": 0 if idx < 3 else 1,
                "shift_event_before": bool(idx == 2),
            }
        )
    return {
        "raw_rows": [],
        "tracked_rows": tracked_rows,
        "shift_events": [
            {
                "boundary_index": 2,
                "previous_capture_index": 1,
                "next_capture_index": 2,
                "trigger_delta_px": 7.0,
            }
        ],
        "frame_diagnostics": [],
    }


def test_clean_filled_mask_fills_bright_core_gap():
    mask = np.zeros((60, 80), dtype=np.uint8)
    mask[10:50, 18:62] = 255
    mask[22:38, 30:50] = 0

    filled = mod._clean_filled_mask(mask)

    assert filled[30, 40] == 255


def test_apply_nozzle_cutoff_zeros_rows_above_cutoff():
    mask = np.full((10, 12), 255, dtype=np.uint8)
    roi = {"x0": 100, "y0": 200, "x1": 112, "y1": 210, "width": 12, "height": 10}

    trimmed = mod._apply_nozzle_cutoff(mask, roi, cutoff_y_px=206)

    assert np.count_nonzero(trimmed[:6, :]) == 0
    assert np.count_nonzero(trimmed[6:, :]) > 0


def test_select_primary_component_prefers_nozzle_anchored_body_over_side_blob():
    mask = np.zeros((80, 120), dtype=np.uint8)
    mask[12:72, 55:67] = 255
    mask[30:79, 4:46] = 255
    roi = {"x0": 100, "y0": 200, "x1": 220, "y1": 280, "width": 120, "height": 80}

    selection = mod._select_primary_component(
        mask,
        roi,
        tracked_x_px=160.0,
        cutoff_y_px=212,
        min_component_area_px=20,
    )

    selected = selection["selected_component"]
    assert selected is not None
    assert 154 <= int(selected["bbox_x_px"]) <= 156
    assert int(selected["top_y_px"]) == 212


def test_accepted_detached_components_excludes_far_side_blob():
    mask = np.zeros((120, 140), dtype=np.uint8)
    mask[12:86, 66:74] = 255
    cv2.circle(mask, (18, 92), 16, 255, thickness=-1)
    roi = {"x0": 100, "y0": 200, "x1": 240, "y1": 320, "width": 140, "height": 120}

    selection = mod._select_primary_component(
        mask,
        roi,
        tracked_x_px=170.0,
        cutoff_y_px=212,
        min_component_area_px=20,
    )
    detached = mod._accepted_detached_components(selection, roi, cutoff_y_px=212)

    assert selection["selected_component"] is not None
    assert detached == []


def test_accepted_detached_components_assigns_deterministic_component_ids():
    mask = np.zeros((160, 120), dtype=np.uint8)
    mask[10:88, 56:64] = 255
    cv2.ellipse(mask, (60, 110), (12, 18), 0.0, 0.0, 360.0, 255, thickness=-1)
    cv2.ellipse(mask, (62, 146), (10, 10), 0.0, 0.0, 360.0, 255, thickness=-1)
    roi = {"x0": 100, "y0": 200, "x1": 220, "y1": 360, "width": 120, "height": 160}

    selection = mod._select_primary_component(
        mask,
        roi,
        tracked_x_px=160.0,
        cutoff_y_px=212,
        min_component_area_px=20,
    )
    detached = mod._accepted_detached_components(selection, roi, cutoff_y_px=212)

    assert selection["selected_component"] is not None
    assert [row["component_id"] for row in detached] == ["detached_01", "detached_02"]
    assert [row["component_rank"] for row in detached] == [1, 2]
    assert [int(row["top_y_px"]) for row in detached] == sorted(int(row["top_y_px"]) for row in detached)


def test_trace_edges_returns_rowwise_bounds_for_selected_component():
    mask = np.zeros((30, 40), dtype=np.uint8)
    mask[10:18, 6:16] = 255
    roi = {"x0": 50, "y0": 80, "x1": 90, "y1": 110, "width": 40, "height": 30}

    rows = mod._trace_edges(mask, roi, {"run_id": "run_a", "capture_id": "cap_1", "capture_index": 1, "flash_delay_us": 4750})

    assert len(rows) == 8
    assert rows[0]["y_px"] == 90
    assert rows[0]["x_left_px"] == 56
    assert rows[0]["x_right_px"] == 65
    assert rows[0]["width_px"] == 10


def test_refine_selected_fill_switches_to_row_envelope_for_open_bottom_interior():
    selected_mask = np.zeros((60, 80), dtype=np.uint8)
    selected_mask[6:56, 22:28] = 255
    selected_mask[6:56, 46:52] = 255
    selected_mask[6:14, 22:52] = 255
    roi = {"x0": 100, "y0": 200, "x1": 180, "y1": 260, "width": 80, "height": 60}

    refinement = mod._refine_selected_fill(
        selected_mask,
        roi,
        tracked_x_px=140.0,
        cutoff_y_px=206,
    )

    assert refinement["open_bottom_interior_detected"] is True
    assert refinement["fill_strategy"] == "row_envelope_fill"
    assert refinement["fill_trigger_source"] == "tracked_center_gap"
    assert refinement["row_fill_added_pixel_count"] > 0
    assert refinement["final_mask"][30, 40] == 255
    assert refinement["final_mask"][55, 40] == 255


def test_refine_selected_fill_uses_background_component_fallback_for_offset_open_bottom_interior():
    selected_mask = np.zeros((60, 80), dtype=np.uint8)
    selected_mask[6:60, 18:62] = 255
    selected_mask[30:60, 24:34] = 0
    roi = {"x0": 100, "y0": 200, "x1": 180, "y1": 260, "width": 80, "height": 60}

    refinement = mod._refine_selected_fill(
        selected_mask,
        roi,
        tracked_x_px=145.0,
        cutoff_y_px=206,
    )

    assert refinement["open_bottom_interior_detected"] is True
    assert refinement["fill_strategy"] == "row_envelope_fill"
    assert refinement["fill_trigger_source"] == "background_component_fallback"
    assert refinement["row_fill_added_pixel_count"] > 0
    assert refinement["fallback_component"]["x0_local"] == 24
    assert refinement["fallback_component"]["x1_local"] == 33
    assert refinement["final_mask"][45, 28] == 255


def test_refine_selected_fill_ignores_bottom_background_that_touches_side_border():
    selected_mask = np.zeros((60, 80), dtype=np.uint8)
    selected_mask[6:60, 5:75] = 255
    selected_mask[30:60, 52:80] = 0
    roi = {"x0": 100, "y0": 200, "x1": 180, "y1": 260, "width": 80, "height": 60}

    refinement = mod._refine_selected_fill(
        selected_mask,
        roi,
        tracked_x_px=135.0,
        cutoff_y_px=206,
    )

    assert refinement["open_bottom_interior_detected"] is False
    assert refinement["fill_strategy"] == "binary_hole_fill"
    assert refinement["fill_trigger_source"] == "none"
    assert refinement["row_fill_added_pixel_count"] == 0
    assert refinement["fallback_component"] is None


def test_refine_selected_fill_prefers_more_bounded_bottom_component_when_multiple_exist():
    selected_mask = np.zeros((80, 100), dtype=np.uint8)
    selected_mask[8:80, 10:92] = 255
    selected_mask[24:80, 28:38] = 0
    selected_mask[52:80, 60:66] = 0
    roi = {"x0": 100, "y0": 200, "x1": 200, "y1": 280, "width": 100, "height": 80}

    refinement = mod._refine_selected_fill(
        selected_mask,
        roi,
        tracked_x_px=172.0,
        cutoff_y_px=210,
    )

    assert refinement["fill_trigger_source"] == "background_component_fallback"
    assert refinement["fallback_component"]["x0_local"] == 28
    assert refinement["fallback_component"]["x1_local"] == 37
    assert refinement["fallback_component"]["bounded_row_count"] > 40


def test_refine_selected_fill_keeps_binary_fill_strategy_for_already_filled_body():
    selected_mask = np.zeros((60, 80), dtype=np.uint8)
    selected_mask[6:56, 22:52] = 255
    roi = {"x0": 100, "y0": 200, "x1": 180, "y1": 260, "width": 80, "height": 60}

    refinement = mod._refine_selected_fill(
        selected_mask,
        roi,
        tracked_x_px=140.0,
        cutoff_y_px=206,
    )

    assert refinement["open_bottom_interior_detected"] is False
    assert refinement["fill_strategy"] == "binary_hole_fill"
    assert refinement["fill_trigger_source"] == "none"
    assert refinement["row_fill_added_pixel_count"] == 0
    assert np.array_equal(refinement["final_mask"], selected_mask)


def test_export_stage3_silhouette_writes_metrics_and_edges(tmp_path, monkeypatch):
    exp_dir, run_dir = _make_silhouette_experiment(tmp_path)
    out_dir = tmp_path / "analysis" / "stream_characterization"
    monkeypatch.setattr(mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage3_silhouette(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    assert payload["selected_run_count"] == 1
    run_info = payload["runs"][0]
    assert run_info["run_id"] == run_dir.name

    metrics_csv = Path(run_info["silhouette_metrics_csv"])
    component_csv = Path(run_info["component_metrics_csv"])
    edges_csv = Path(run_info["edge_traces_csv"])
    edges_json = Path(run_info["edge_traces_json"])
    contact_sheet_png = Path(run_info["sample_contact_sheet_png"])

    assert metrics_csv.exists()
    assert component_csv.exists()
    assert edges_csv.exists()
    assert edges_json.exists()
    assert contact_sheet_png.exists()

    with metrics_csv.open("r", encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))
    with component_csv.open("r", encoding="utf-8", newline="") as handle:
        component_rows = list(csv.DictReader(handle))
    with edges_csv.open("r", encoding="utf-8", newline="") as handle:
        edge_rows = list(csv.DictReader(handle))

    assert len(metric_rows) == 3
    assert component_rows
    assert edge_rows
    assert all(row["silhouette_status"] == "ok" for row in metric_rows)
    assert float(metric_rows[1]["tracked_confidence"]) == 0.41
    assert metric_rows[1]["final_mode"] == "segment_fill"
    assert metric_rows[1]["shift_event_before"] == "True"
    assert int(metric_rows[0]["valid_row_count"]) > 0
    assert all("fill_strategy" in row for row in metric_rows)
    assert all("fill_trigger_source" in row for row in metric_rows)
    assert all("open_bottom_interior_detected" in row for row in metric_rows)
    assert all("row_fill_added_pixel_count" in row for row in metric_rows)
    assert all("accepted_component_count" in row for row in metric_rows)
    assert all("accepted_detached_component_count" in row for row in metric_rows)
    assert all(row["component_id"] == "attached_primary" for row in component_rows)
    assert all("component_id" in row for row in edge_rows)
    assert all("component_role" in row for row in edge_rows)
    assert all("component_rank" in row for row in edge_rows)

    edge_payload = json.loads(edges_json.read_text(encoding="utf-8"))
    assert edge_payload["run_id"] == run_dir.name
    assert edge_payload["row_count"] == len(edge_rows)


def test_export_stage3_silhouette_includes_accepted_detached_components(tmp_path, monkeypatch):
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
    monkeypatch.setattr(mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage3_silhouette(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    metrics_csv = Path(payload["runs"][0]["silhouette_metrics_csv"])
    component_csv = Path(payload["runs"][0]["component_metrics_csv"])
    edges_csv = Path(payload["runs"][0]["edge_traces_csv"])

    with metrics_csv.open("r", encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))
    with component_csv.open("r", encoding="utf-8", newline="") as handle:
        component_rows = list(csv.DictReader(handle))
    with edges_csv.open("r", encoding="utf-8", newline="") as handle:
        edge_rows = list(csv.DictReader(handle))

    frame2_metric = next(row for row in metric_rows if int(row["capture_index"]) == 2)
    frame2_components = [row for row in component_rows if int(row["capture_index"]) == 2]
    frame2_edges = [row for row in edge_rows if int(row["capture_index"]) == 2]

    assert int(frame2_metric["accepted_component_count"]) == 2
    assert int(frame2_metric["accepted_detached_component_count"]) == 1
    assert {row["component_id"] for row in frame2_components} == {"attached_primary", "detached_01"}
    assert {row["component_role"] for row in frame2_components} == {"attached_primary", "detached_accepted"}
    assert {row["component_id"] for row in frame2_edges} == {"attached_primary", "detached_01"}


def test_export_stage3_silhouette_uses_row_fill_for_open_bottom_stream(tmp_path, monkeypatch):
    exp_dir, _run_dir = _make_silhouette_experiment(tmp_path, open_bottom_indices={3})
    out_dir = tmp_path / "analysis" / "stream_characterization"
    monkeypatch.setattr(mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage3_silhouette(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    metrics_csv = Path(payload["runs"][0]["silhouette_metrics_csv"])
    edges_csv = Path(payload["runs"][0]["edge_traces_csv"])

    with metrics_csv.open("r", encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))
    with edges_csv.open("r", encoding="utf-8", newline="") as handle:
        edge_rows = list(csv.DictReader(handle))

    row_fill_rows = [row for row in metric_rows if row["fill_strategy"] == "row_envelope_fill"]
    assert row_fill_rows
    assert any(row["open_bottom_interior_detected"] == "True" for row in row_fill_rows)
    assert any(int(row["row_fill_added_pixel_count"]) > 0 for row in row_fill_rows)
    assert any(row["fill_trigger_source"] == "tracked_center_gap" for row in row_fill_rows)

    frame3_edges = [row for row in edge_rows if int(row["capture_index"]) == 3]
    assert frame3_edges
    assert any(int(row["width_px"]) >= 20 for row in frame3_edges)


def test_export_stage3_silhouette_uses_fallback_for_offset_open_bottom_stream(tmp_path, monkeypatch):
    exp_dir, _run_dir = _make_silhouette_experiment(
        tmp_path,
        open_bottom_indices={3},
        open_bottom_offsets={3: -20},
    )
    out_dir = tmp_path / "analysis" / "stream_characterization"
    monkeypatch.setattr(mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage3_silhouette(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    metrics_csv = Path(payload["runs"][0]["silhouette_metrics_csv"])

    with metrics_csv.open("r", encoding="utf-8", newline="") as handle:
        metric_rows = list(csv.DictReader(handle))

    frame3_row = next(row for row in metric_rows if int(row["capture_index"]) == 3)
    assert frame3_row["fill_strategy"] == "row_envelope_fill"
    assert frame3_row["fill_trigger_source"] == "background_component_fallback"
    assert frame3_row["open_bottom_interior_detected"] == "True"
    assert int(frame3_row["row_fill_added_pixel_count"]) > 0


def test_export_stage3_silhouette_refines_detached_open_bottom_component(tmp_path, monkeypatch):
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
    monkeypatch.setattr(mod, "_build_stage2_run", _fake_stage2_run)

    payload = mod.export_stage3_silhouette(
        exp_dir,
        output_root=out_dir,
        sample_count=3,
        nozzle_guard_px=2,
        min_component_area_px=50,
    )

    component_csv = Path(payload["runs"][0]["component_metrics_csv"])
    with component_csv.open("r", encoding="utf-8", newline="") as handle:
        component_rows = list(csv.DictReader(handle))

    detached_row = next(
        row
        for row in component_rows
        if int(row["capture_index"]) == 2 and row["component_id"] == "detached_01"
    )
    assert detached_row["fill_strategy"] == "row_envelope_fill"
    assert detached_row["open_bottom_interior_detected"] == "True"
    assert int(detached_row["row_fill_added_pixel_count"]) > 0
