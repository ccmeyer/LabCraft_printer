import csv
import json
from pathlib import Path

import pytest

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_chroma_edge_offset_cache as cache_mod
from tools.stream_analysis import online_chroma_edge_cap_sweep as mod
from tools.stream_analysis import online_chroma_edge_prototype as proto_mod


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key in seen:
                continue
            seen.add(key)
            fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_metadata_csv(exp_dir: Path, rows):
    fieldnames = [
        "Dataset name",
        "Print PW",
        "Print Pressure",
        "Rep",
        "Mass/print",
        "Num printed",
        "Capture Process",
        "Predicted Volume (nL)",
        "Analysis Warnings",
    ]
    path = exp_dir / dataset_mod.METADATA_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _edge_row(y_px: int, *, x_left: int = 120, x_right: int = 150):
    return {
        "y_px": int(y_px),
        "x_left_px": int(x_left),
        "x_right_px": int(x_right),
        "width_px": int(x_right - x_left + 1),
        "center_x_px": float(x_left + x_right) / 2.0,
    }


def _feature(
    y_px: int,
    side: str,
    offset_px: int,
    *,
    current_x_px: int | None = None,
    sample_in_bounds: bool = True,
    sample_is_excluded: bool = True,
    contiguous_to_attached_mask: bool = True,
    intermediate_pixels_all_excluded: bool = True,
    gray_headroom: float = 10.0,
    delta_lab_chroma: float = -8.0,
    edge_bg_gap: float = 60.0,
):
    if current_x_px is None:
        current_x_px = 120 if side == "left" else 150
    return {
        "y_px": int(y_px),
        "side": str(side),
        "current_x_px": int(current_x_px),
        "sample_offset_px": int(offset_px),
        "sample_in_bounds": bool(sample_in_bounds),
        "sample_is_excluded": bool(sample_is_excluded),
        "contiguous_to_attached_mask": bool(contiguous_to_attached_mask),
        "intermediate_pixels_all_excluded": bool(intermediate_pixels_all_excluded),
        "gray_headroom": float(gray_headroom),
        "delta_lab_chroma": float(delta_lab_chroma),
        "edge_bg_gap": float(edge_bg_gap),
    }


def _proto_feature(y_px: int, side: str, *, current_x_px: int | None = None):
    if current_x_px is None:
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
        "gray_edge": 130,
        "gray_outside": 150,
        "gray_headroom": 10.0,
        "edge_bg_gap": 60.0,
        "delta_lab_chroma": -8.0,
    }


def _archived_frame_row(
    *,
    phase: str,
    delay_from_emergence_us: int,
    capture_index: int,
    visible_volume_nl: float,
    attached_width_px: float,
    warnings=None,
    separated_from_nozzle_landmark: bool = False,
):
    delay_us = int(1000 + delay_from_emergence_us)
    capture_id = f"cap_{capture_index:06d}"
    return {
        "phase": phase,
        "status": "accepted",
        "delay_us": delay_us,
        "flash_delay_us": delay_us,
        "delay_from_emergence_us": int(delay_from_emergence_us),
        "replicate_index": 1,
        "capture_index": int(capture_index),
        "attached_width_px": float(attached_width_px),
        "visible_volume_nl": float(visible_volume_nl),
        "attached_bottom_clearance_px": 120.0,
        "min_accepted_fluid_distance_from_bottom_px": 120.0,
        "warnings": list(warnings or []),
        "qc": {"measurement_qc_pass": True, "nozzle_qc_pass": True, "silhouette_qc_pass": True},
        "flow_measurement_usable": True,
        "attached_bottom_guard_hit": False,
        "detached_near_bottom_warning": False,
        "near_nozzle_detached_warning": False,
        "late_frame_warning": False,
        "image_ref": {
            "capture_id": capture_id,
            "capture_index": int(capture_index),
            "image_relpath": f"captures/{capture_id}_{phase}.jpg",
        },
        "separated_from_nozzle_landmark": bool(separated_from_nozzle_landmark),
    }


def test_cap_semantics_require_contiguous_eligible_offsets():
    edge_rows = [_edge_row(300)]
    features = [
        _feature(300, "left", 1),
        _feature(300, "left", 2, edge_bg_gap=10.0),
        _feature(300, "left", 3),
        _feature(300, "right", 1, sample_in_bounds=False),
        _feature(300, "right", 2),
        _feature(300, "right", 3),
    ]
    rule = {
        "gray_headroom_px": 40,
        "delta_lab_chroma_max": -4.0,
        "edge_bg_gap_min": 45,
        "continuity_min_support": 1,
    }

    move_map = mod._max_contiguous_move_map(edge_rows, features, max_offset_px=3, rule=rule)

    assert move_map[(300, "left")] == 1
    assert move_map[(300, "right")] == 0


def test_continuity_is_evaluated_per_offset_not_borrowed_from_offset_one():
    edge_rows = [_edge_row(300 + idx) for idx in range(5)]
    features = []
    for y_px in range(300, 305):
        features.append(_feature(y_px, "right", 1))
    features.append(_feature(302, "right", 2))
    rule = {
        "gray_headroom_px": 40,
        "delta_lab_chroma_max": -4.0,
        "edge_bg_gap_min": 45,
        "continuity_min_support": 2,
    }

    move_map = mod._max_contiguous_move_map(edge_rows, features, max_offset_px=2, rule=rule)

    assert move_map[(302, "right")] == 1


def test_cap_one_matches_direct_single_offset_v2_correction():
    edge_rows = [_edge_row(300 + idx) for idx in range(5)]
    cache_features = []
    proto_features = []
    for y_px in range(300, 305):
        cache_features.extend([_feature(y_px, "left", 1), _feature(y_px, "right", 1)])
        proto_features.extend([_proto_feature(y_px, "left"), _proto_feature(y_px, "right")])

    rule = {
        "candidate_id": "test_rule",
        "gray_headroom_px": 40,
        "delta_lab_chroma_max": -4.0,
        "edge_bg_gap_min": 45,
        "continuity_min_support": 2,
    }
    move_map = mod._max_contiguous_move_map(edge_rows, cache_features, max_offset_px=1, rule=rule)
    corrected_rows, *_rest = mod._corrected_edge_rows_for_cap(
        edge_rows,
        move_map=move_map,
        cap_px=1,
        roi={"x0": 100, "x1": 200},
    )

    decisions = proto_mod._evaluate_rule_on_row_side_features(proto_features, rule)
    direct_rows = proto_mod._apply_edge_correction(edge_rows, decisions, {"x0": 100, "x1": 200})

    assert corrected_rows == direct_rows
    assert proto_mod._edge_rows_volume_nl(corrected_rows) == pytest.approx(
        proto_mod._edge_rows_volume_nl(direct_rows)
    )


def test_corrected_frame_row_preserves_archived_fields_and_recomputes_metrics():
    edge_rows = [_edge_row(300 + idx) for idx in range(5)]
    frame_summary = {
        "delay_us": 4000,
        "delay_from_emergence_us": 3000,
        "current_attached_volume_nl": proto_mod._edge_rows_volume_nl(edge_rows),
        "current_total_visible_volume_nl": proto_mod._edge_rows_volume_nl(edge_rows) + 0.5,
        "detached_visible_volume_nl": 0.5,
        "roi": {"x0": 100, "y0": 250, "x1": 200, "y1": 360, "width": 100, "height": 110},
    }
    archived_row = _archived_frame_row(
        phase="flow_rate",
        delay_from_emergence_us=3000,
        capture_index=1,
        visible_volume_nl=10.0,
        attached_width_px=60.0,
        warnings=["kept"],
    )
    move_map = {(int(row["y_px"]), side): 2 for row in edge_rows for side in ("left", "right")}

    corrected_row = mod._corrected_frame_row_from_cache(
        archived_row,
        frame_summary,
        edge_rows,
        move_map=move_map,
        cap_px=2,
        rule={"candidate_id": "rule"},
        nozzle_center_px=[150, 250],
        analysis_config={
            "near_nozzle_band_top_px": 40,
            "near_nozzle_band_height_px": 40,
            "min_band_valid_rows": 1,
        },
    )

    assert corrected_row["phase"] == "flow_rate"
    assert corrected_row["warnings"] == ["kept"]
    assert corrected_row["visible_volume_nl"] > frame_summary["current_total_visible_volume_nl"]
    assert corrected_row["attached_visible_volume_nl"] > frame_summary["current_attached_volume_nl"]
    assert corrected_row["attached_width_px"] is not None
    assert corrected_row["correction_cap_px"] == 2
    assert corrected_row["correction_max_row_side_move_px"] == 2


def test_cap_zero_returns_baseline_geometry_and_volumes():
    edge_rows = [_edge_row(300 + idx) for idx in range(5)]
    attached_volume_nl = proto_mod._edge_rows_volume_nl(edge_rows)
    frame_summary = {
        "delay_us": 4000,
        "delay_from_emergence_us": 3000,
        "current_attached_volume_nl": attached_volume_nl,
        "current_total_visible_volume_nl": attached_volume_nl,
        "detached_visible_volume_nl": 0.0,
        "roi": {"x0": 100, "y0": 250, "x1": 200, "y1": 360, "width": 100, "height": 110},
    }
    archived_row = _archived_frame_row(
        phase="flow_rate",
        delay_from_emergence_us=3000,
        capture_index=1,
        visible_volume_nl=10.0,
        attached_width_px=60.0,
    )
    move_map = {(int(row["y_px"]), side): 3 for row in edge_rows for side in ("left", "right")}

    corrected_row = mod._corrected_frame_row_from_cache(
        archived_row,
        frame_summary,
        edge_rows,
        move_map=move_map,
        cap_px=0,
        rule={"candidate_id": "rule"},
        nozzle_center_px=[150, 250],
        analysis_config={
            "near_nozzle_band_top_px": 40,
            "near_nozzle_band_height_px": 40,
            "min_band_valid_rows": 1,
        },
    )

    assert corrected_row["attached_visible_volume_nl"] == pytest.approx(attached_volume_nl)
    assert corrected_row["visible_volume_nl"] == pytest.approx(attached_volume_nl)
    assert corrected_row["correction_max_row_side_move_px"] == 0


def test_corrected_attached_volume_is_monotonic_with_increasing_cap():
    edge_rows = [_edge_row(300 + idx) for idx in range(5)]
    frame_summary = {
        "delay_us": 4000,
        "delay_from_emergence_us": 3000,
        "current_attached_volume_nl": proto_mod._edge_rows_volume_nl(edge_rows),
        "current_total_visible_volume_nl": proto_mod._edge_rows_volume_nl(edge_rows),
        "detached_visible_volume_nl": 0.0,
        "roi": {"x0": 100, "y0": 250, "x1": 200, "y1": 360, "width": 100, "height": 110},
    }
    archived_row = _archived_frame_row(
        phase="flow_rate",
        delay_from_emergence_us=3000,
        capture_index=1,
        visible_volume_nl=10.0,
        attached_width_px=60.0,
    )
    move_map = {(int(row["y_px"]), side): 3 for row in edge_rows for side in ("left", "right")}
    attached_volumes = []
    for cap_px in (0, 1, 2, 3):
        corrected_row = mod._corrected_frame_row_from_cache(
            archived_row,
            frame_summary,
            edge_rows,
            move_map=move_map,
            cap_px=cap_px,
            rule={"candidate_id": "rule"},
            nozzle_center_px=[150, 250],
            analysis_config={
                "near_nozzle_band_top_px": 40,
                "near_nozzle_band_height_px": 40,
                "min_band_valid_rows": 1,
            },
        )
        attached_volumes.append(float(corrected_row["attached_visible_volume_nl"]))
    assert attached_volumes == sorted(attached_volumes)


def _make_cached_experiment_fixture(tmp_path: Path):
    exp_dir = tmp_path / "Stream_cap_sweep-20260411_120000"
    process_root = exp_dir / "calibration_recordings" / dataset_mod.ONLINE_STREAM_PROCESS_NAME
    run_id = "run_001"
    run_dir = process_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        run_dir / "run_meta.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "process_name": dataset_mod.ONLINE_STREAM_PROCESS_NAME,
            "phase_name": "online_stream_calibration",
            "outcome": "completed",
            "error_message": "",
        },
    )
    _write_json(
        run_dir / "plan_snapshot.json",
        {
            "schema_version": 1,
            "condition": {
                "emergence_time_us": 1000,
                "print_pressure_psi": 1.0,
                "print_pulse_width_us": 3000,
            },
            "analysis_config": {
                "near_nozzle_band_top_px": 40,
                "near_nozzle_band_height_px": 40,
                "min_band_valid_rows": 1,
            },
        },
    )

    archived_rows = []
    capture_index = 1
    for step_index in range(12):
        delay_from_emergence_us = 3000 + (100 * step_index)
        width_px = 60.0 + float(step_index)
        visible_volume_nl = 60.0 + (5.0 * float(step_index))
        archived_rows.append(
            _archived_frame_row(
                phase="flow_rate",
                delay_from_emergence_us=delay_from_emergence_us,
                capture_index=capture_index,
                visible_volume_nl=visible_volume_nl,
                attached_width_px=width_px,
            )
        )
        capture_index += 1
    archived_rows.extend(
        [
            _archived_frame_row(phase="tail_scout", delay_from_emergence_us=4300, capture_index=capture_index, visible_volume_nl=118.0, attached_width_px=71.0),
            _archived_frame_row(phase="tail_scout", delay_from_emergence_us=4700, capture_index=capture_index + 1, visible_volume_nl=122.0, attached_width_px=64.0),
            _archived_frame_row(phase="tail_backtrack", delay_from_emergence_us=4200, capture_index=capture_index + 2, visible_volume_nl=116.0, attached_width_px=70.0),
            _archived_frame_row(phase="tail_backtrack", delay_from_emergence_us=4400, capture_index=capture_index + 3, visible_volume_nl=119.0, attached_width_px=67.0),
            _archived_frame_row(phase="tail_backtrack", delay_from_emergence_us=4700, capture_index=capture_index + 4, visible_volume_nl=123.0, attached_width_px=63.0, separated_from_nozzle_landmark=True),
        ]
    )
    _write_jsonl(run_dir / "frames.jsonl", archived_rows)

    _write_json(
        run_dir / "flow_fit.json",
        {
            "fit": {
                "fit_status": "ok",
                "flow_rate_nl_per_us": 0.02,
                "flow_intercept_nl": 0.0,
                "steady_rate_ci95_low_nl_per_us": 0.019,
                "steady_rate_ci95_high_nl_per_us": 0.021,
                "steady_rate_ci95_relative_width": 0.10,
                "steady_width_baseline_px": 71.0,
            }
        },
    )
    _write_json(
        run_dir / "tail_fit.json",
        {
            "tail_plan": {
                "search_method": "separation_landmark_backtrack_v1",
                "scout_anchor_delay_us": 3900,
            },
            "result": {
                "predicted_volume_nl": 84.0,
                "tail_phase": {
                    "status": "ok",
                    "tail_start_selection_method": "earliest_transition_before_confirmed_collapse",
                    "tail_start_delay_from_emergence_us": 4400,
                    "confirmed_collapse_delay_from_emergence_us": 4500,
                    "last_plateau_delay_from_emergence_us": 4300,
                    "landmark_reason": "separated_from_nozzle",
                },
            },
        },
    )

    metadata_row = {
        "Dataset name": run_id,
        "Print PW": "3000",
        "Print Pressure": "1.0",
        "Rep": "1",
        "Mass/print": "0.085",
        "Num printed": "10",
        "Capture Process": dataset_mod.ONLINE_STREAM_PROCESS_NAME,
        "Predicted Volume (nL)": "84.0",
        "Analysis Warnings": "",
    }
    _write_metadata_csv(exp_dir, [metadata_row])

    frame_summary_rows = []
    baseline_edge_rows = []
    offset_feature_rows = []
    for row in archived_rows:
        capture_id = row["image_ref"]["capture_id"]
        capture_index = int(row["capture_index"])
        width_px = int(round(float(row["attached_width_px"])))
        x_left = 150 - int(width_px // 2)
        x_right = x_left + int(width_px) - 1
        edges = [_edge_row(290 + idx, x_left=x_left, x_right=x_right) for idx in range(5)]
        attached_volume_nl = proto_mod._edge_rows_volume_nl(edges)
        frame_summary_rows.append(
            {
                "run_id": run_id,
                "capture_id": capture_id,
                "capture_index": capture_index,
                "phase": row["phase"],
                "status": row["status"],
                "delay_us": row["delay_us"],
                "delay_from_emergence_us": row["delay_from_emergence_us"],
                "image_relpath": row["image_ref"]["image_relpath"],
                "threshold_value": 140.0,
                "attached_edge_row_count": len(edges),
                "feature_row_count": len(edges) * 2 * 3,
                "current_attached_volume_nl": attached_volume_nl,
                "current_total_visible_volume_nl": attached_volume_nl,
                "detached_visible_volume_nl": 0.0,
                "roi_x0": 100,
                "roi_y0": 250,
                "roi_x1": 200,
                "roi_y1": 360,
            }
        )
        for edge in edges:
            baseline_edge_rows.append(
                {
                    "run_id": run_id,
                    "capture_id": capture_id,
                    "capture_index": capture_index,
                    "delay_us": row["delay_us"],
                    "delay_from_emergence_us": row["delay_from_emergence_us"],
                    **edge,
                }
            )
            for side in ("left", "right"):
                current_x = edge["x_left_px"] if side == "left" else edge["x_right_px"]
                for offset_px in (1, 2, 3):
                    offset_feature_rows.append(
                        {
                            "run_id": run_id,
                            "capture_id": capture_id,
                            "capture_index": capture_index,
                            "delay_us": row["delay_us"],
                            "delay_from_emergence_us": row["delay_from_emergence_us"],
                            "y_px": edge["y_px"],
                            "side": side,
                            "current_x_px": current_x,
                            "sample_offset_px": offset_px,
                            "sample_x_px": current_x + (-offset_px if side == "left" else offset_px),
                            "sample_in_bounds": True,
                            "contiguous_to_attached_mask": True,
                            "sample_is_excluded": True,
                            "intermediate_pixels_all_excluded": True,
                            "intermediate_excluded_count": offset_px,
                            "threshold_value": 140.0,
                            "gray_headroom": 10.0,
                            "delta_lab_chroma": -8.0,
                            "edge_bg_gap": 60.0,
                        }
                    )

    analysis_root = exp_dir / "analysis" / "online_chroma_edge_offset_cache_p1_max3"
    run_output_root = analysis_root / "runs" / run_id
    frame_summary_csv = run_output_root / "frame_summary.csv"
    baseline_edge_rows_csv = run_output_root / "baseline_edge_rows.csv"
    row_side_offset_features_csv = run_output_root / "row_side_offset_features.csv"
    _write_csv(frame_summary_csv, frame_summary_rows)
    _write_csv(baseline_edge_rows_csv, baseline_edge_rows)
    _write_csv(row_side_offset_features_csv, offset_feature_rows)

    run_manifest = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "print_pressure": 1.0,
        "print_pw_us": 3000,
        "replicate_index": 1,
        "mass_per_print_mg": 0.085,
        "max_offset_px": 3,
        "correction_context": {
            "run_id": run_id,
            "online_run_dir": str(run_dir),
            "emergence_run_dir": str(exp_dir / "calibration_recordings" / "DropletEmergenceCalibrationProcess" / "run_emergence"),
            "emergence_run_id": "run_emergence",
            "emergence_time_us": 1000,
            "nozzle_center_px": [150, 250],
            "resolved_from_stream_capture_log": True,
            "selected_rule": {
                "candidate_id": "gh40_dlc-4_ebg45_sup2",
                "gray_headroom_px": 40,
                "delta_lab_chroma_max": -4.0,
                "edge_bg_gap_min": 45,
                "continuity_min_support": 2,
            },
        },
        "frame_count": len(frame_summary_rows),
        "edge_row_count": len(baseline_edge_rows),
        "feature_row_count": len(offset_feature_rows),
        "paths": {
            "frame_summary_csv": str(frame_summary_csv),
            "baseline_edge_rows_csv": str(baseline_edge_rows_csv),
            "row_side_offset_features_csv": str(row_side_offset_features_csv),
        },
    }
    run_manifest_path = run_output_root / "run_manifest.json"
    _write_json(run_manifest_path, run_manifest)

    cache_manifest = {
        "analysis": cache_mod.STAGE_DIRNAME_PREFIX,
        "experiment_root": str(exp_dir),
        "output_root": str(analysis_root),
        "print_pressure": 1.0,
        "max_offset_px": 3,
        "selected_rule_reference": {
            "candidate_id": "gh40_dlc-4_ebg45_sup2",
            "gray_headroom_px": 40,
            "delta_lab_chroma_max": -4.0,
            "edge_bg_gap_min": 45,
            "continuity_min_support": 2,
        },
        "runs": [
            {
                **run_manifest,
                "run_manifest_json": str(run_manifest_path),
            }
        ],
    }
    cache_manifest_path = analysis_root / "cache_manifest.json"
    _write_json(cache_manifest_path, cache_manifest)
    return exp_dir, cache_manifest_path


def test_export_online_chroma_edge_cap_sweep_writes_artifacts_and_monotonic_summary(tmp_path):
    pytest.importorskip("matplotlib")

    _exp_dir, cache_manifest_path = _make_cached_experiment_fixture(tmp_path)
    payload = mod.export_online_chroma_edge_cap_sweep(
        cache_manifest_path,
        density_g_per_ml=1.0,
        caps="0,1,2,3",
    )

    assert payload["analysis"] == mod.ANALYSIS_NAME
    assert payload["requested_caps_px"] == [0, 1, 2, 3]
    assert Path(payload["paths"]["cap_sweep_manifest_json"]).exists()
    assert Path(payload["paths"]["cap_summary_csv"]).exists()
    assert Path(payload["paths"]["run_cap_summary_csv"]).exists()
    assert Path(payload["paths"]["condition_cap_summary_csv"]).exists()
    assert Path(payload["paths"]["predicted_vs_gravimetric_by_cap_png"]).exists()
    assert Path(payload["paths"]["signed_residual_vs_cap_by_condition_png"]).exists()
    assert Path(payload["paths"]["predicted_to_gravimetric_ratio_vs_cap_by_condition_png"]).exists()
    assert set(payload["cap_report_paths"]) == {0, 1, 2, 3}

    with Path(payload["paths"]["cap_summary_csv"]).open("r", encoding="utf-8", newline="") as handle:
        cap_rows = list(csv.DictReader(handle))
    assert [int(row["cap_px"]) for row in cap_rows] == [0, 1, 2, 3]

    cap_3_manifest = Path(payload["cap_report_paths"][3]["report_manifest_json"])
    assert cap_3_manifest.exists()
