from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_chroma_edge_prototype as proto_mod
from tools.stream_analysis import online_report as report_mod


STAGE_DIRNAME_PREFIX = "online_chroma_edge_offset_cache"
DEFAULT_PRINT_PRESSURE = 1.0
DEFAULT_MAX_OFFSET_PX = 3


def _clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float_or_none(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _int_or_none(value):
    try:
        if value in (None, ""):
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _safe_slug(text: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in str(text)).strip("_")


def _pressure_slug(print_pressure: float | int | None) -> str:
    pressure = _float_or_none(print_pressure)
    if pressure is None:
        return "unknown"
    return f"{float(pressure):0.3f}".rstrip("0").rstrip(".").replace(".", "_")


def _default_output_root(
    experiment_root: Path,
    *,
    print_pressure: float | int | None,
    max_offset_px: int,
) -> Path:
    return (
        experiment_root
        / "analysis"
        / f"{STAGE_DIRNAME_PREFIX}_p{_pressure_slug(print_pressure)}_max{int(max_offset_px)}"
    )


def _matching_metadata_rows(
    experiment_root: Path,
    *,
    print_pressure: float | int | None = None,
    print_pw_us: int | None = None,
    run_id: str | None = None,
) -> list[dict]:
    pressure_value = _float_or_none(print_pressure)
    pw_value = _int_or_none(print_pw_us)
    rows = []
    for row in report_mod._metadata_rows(experiment_root):
        process_name = _clean_text(row.get("Capture Process")) or report_mod.PROCESS_NAME
        if process_name != report_mod.PROCESS_NAME:
            continue
        if run_id is not None and _clean_text(row.get("Dataset name")) != str(run_id):
            continue
        row_pressure = _float_or_none(row.get("Print Pressure"))
        row_pw = _int_or_none(row.get("Print PW"))
        if pressure_value is not None and row_pressure is not None and abs(float(row_pressure) - float(pressure_value)) > 1e-9:
            continue
        if pressure_value is not None and row_pressure is None:
            continue
        if pw_value is not None and row_pw != int(pw_value):
            continue
        rows.append(dict(row))
    return rows


def _descriptor_planes(frame_analysis: dict) -> dict:
    frame_color = np.asarray(frame_analysis["frame_color"])
    gray = np.asarray(frame_analysis["gray"])
    lab_image = cv2.cvtColor(frame_color, cv2.COLOR_BGR2LAB)
    lab_a = lab_image[:, :, 1].astype(np.float32) - 128.0
    lab_b = lab_image[:, :, 2].astype(np.float32) - 128.0
    return {
        "frame_color": frame_color,
        "gray": gray,
        "lab_a": lab_a,
        "lab_b": lab_b,
        "lab_chroma": np.hypot(lab_a, lab_b),
    }


def _pixel_metrics_from_planes(planes: dict, *, y_px: int, x_px: int) -> dict:
    frame_color = np.asarray(planes["frame_color"])
    gray = np.asarray(planes["gray"])
    lab_a = np.asarray(planes["lab_a"])
    lab_b = np.asarray(planes["lab_b"])
    lab_chroma = np.asarray(planes["lab_chroma"])
    b_value = int(frame_color[y_px, x_px, 0])
    g_value = int(frame_color[y_px, x_px, 1])
    r_value = int(frame_color[y_px, x_px, 2])
    return {
        "gray": int(gray[y_px, x_px]),
        "b": int(b_value),
        "g": int(g_value),
        "r": int(r_value),
        "bg_gap": float(b_value - g_value),
        "gr_gap": float(g_value - r_value),
        "br_gap": float(b_value - r_value),
        "rb_chroma": float(abs(int(b_value) - int(r_value))),
        "blue_excess": float(int(b_value) - max(int(g_value), int(r_value))),
        "lab_a": float(lab_a[y_px, x_px]),
        "lab_b": float(lab_b[y_px, x_px]),
        "lab_chroma": float(lab_chroma[y_px, x_px]),
    }


def _component_baseline_edge_rows(
    frame_analysis: dict,
    *,
    component_kind: str,
    component_id: str,
    edge_rows: list[dict],
) -> list[dict]:
    rows = []
    run_id = _clean_text((frame_analysis.get("run_dir") or Path("")).name)
    for row in list(edge_rows or []):
        rows.append(
            {
                "run_id": run_id,
                "capture_id": _clean_text(frame_analysis.get("capture_id")),
                "capture_index": frame_analysis.get("capture_index"),
                "delay_us": int(frame_analysis["delay_us"]),
                "delay_from_emergence_us": int(frame_analysis["delay_from_emergence_us"]),
                "component_kind": str(component_kind),
                "component_id": str(component_id),
                "y_px": int(row["y_px"]),
                "x_left_px": int(row["x_left_px"]),
                "x_right_px": int(row["x_right_px"]),
                "width_px": int(row["width_px"]),
                "center_x_px": float(row["center_x_px"]),
            }
        )
    return rows


def _extract_component_row_side_offset_features(
    frame_analysis: dict,
    *,
    component_kind: str,
    component_id: str,
    component_mask,
    edge_rows: list[dict],
    move_directions: tuple[str, ...],
    max_offset_px: int,
) -> list[dict]:
    roi = dict(frame_analysis["roi"])
    resolved_component_mask = proto_mod._ensure_mask(
        component_mask,
        shape=(int(roi["height"]), int(roi["width"])),
    )
    threshold_value = frame_analysis.get("threshold_value")
    planes = _descriptor_planes(frame_analysis)
    features = []
    for edge_row in list(edge_rows or []):
        y_px = int(edge_row["y_px"])
        local_y = int(y_px - int(roi["y0"]))
        if local_y < 0 or local_y >= resolved_component_mask.shape[0]:
            continue
        for side in ("left", "right"):
            current_x_px = int(edge_row["x_left_px"] if side == "left" else edge_row["x_right_px"])
            current_local_x = int(current_x_px - int(roi["x0"]))
            current_in_bounds = bool(
                int(roi["x0"]) <= int(current_x_px) < int(roi["x1"])
                and 0 <= int(current_local_x) < resolved_component_mask.shape[1]
            )
            edge_metrics = (
                _pixel_metrics_from_planes(planes, y_px=y_px, x_px=current_x_px)
                if current_in_bounds
                else None
            )
            contiguous_to_component_mask = bool(
                current_in_bounds and resolved_component_mask[local_y, current_local_x] > 0
            )
            for move_direction in move_directions:
                if str(move_direction) not in {"outward", "inward"}:
                    continue
                direction = -1 if side == "left" else 1
                if str(move_direction) == "inward":
                    direction *= -1
                for offset_px in range(1, int(max_offset_px) + 1):
                    sample_x_px = int(current_x_px + (direction * int(offset_px)))
                    sample_local_x = int(sample_x_px - int(roi["x0"]))
                    sample_in_bounds = bool(
                        int(roi["x0"]) <= int(sample_x_px) < int(roi["x1"])
                        and 0 <= int(sample_local_x) < resolved_component_mask.shape[1]
                    )
                    sample_metrics = (
                        _pixel_metrics_from_planes(planes, y_px=y_px, x_px=sample_x_px)
                        if sample_in_bounds
                        else None
                    )
                    sample_is_included = bool(
                        sample_in_bounds and resolved_component_mask[local_y, sample_local_x] > 0
                    )
                    sample_is_excluded = bool(sample_in_bounds and not sample_is_included)
                    intermediate_offsets = list(range(1, int(offset_px) + 1))
                    intermediate_positions = [
                        int(current_x_px + (direction * value))
                        for value in intermediate_offsets
                    ]
                    intermediate_in_bounds = all(
                        int(roi["x0"]) <= int(position) < int(roi["x1"])
                        for position in intermediate_positions
                    )
                    intermediate_pixels_all_excluded = bool(intermediate_in_bounds)
                    intermediate_pixels_all_included = bool(intermediate_in_bounds)
                    intermediate_excluded_count = 0
                    intermediate_included_count = 0
                    for position in intermediate_positions:
                        local_x = int(position - int(roi["x0"]))
                        if not (0 <= local_x < resolved_component_mask.shape[1]):
                            intermediate_pixels_all_excluded = False
                            intermediate_pixels_all_included = False
                            continue
                        included = bool(resolved_component_mask[local_y, local_x] > 0)
                        excluded = bool(not included)
                        intermediate_excluded_count += 1 if excluded else 0
                        intermediate_included_count += 1 if included else 0
                        intermediate_pixels_all_excluded = bool(
                            intermediate_pixels_all_excluded and excluded
                        )
                        intermediate_pixels_all_included = bool(
                            intermediate_pixels_all_included and included
                        )

                    gray_edge = None if edge_metrics is None else int(edge_metrics["gray"])
                    gray_sample = None if sample_metrics is None else int(sample_metrics["gray"])
                    gray_headroom = None
                    edge_gray_margin = None
                    sample_gray_drop = None
                    if gray_sample is not None and threshold_value is not None:
                        gray_headroom = float(gray_sample) - float(threshold_value)
                    if gray_edge is not None and threshold_value is not None:
                        edge_gray_margin = float(threshold_value) - float(gray_edge)
                    if gray_edge is not None and gray_sample is not None:
                        sample_gray_drop = float(gray_edge) - float(gray_sample)
                    delta_lab_chroma = None
                    if edge_metrics is not None and sample_metrics is not None:
                        delta_lab_chroma = float(sample_metrics["lab_chroma"]) - float(
                            edge_metrics["lab_chroma"]
                        )
                    features.append(
                        {
                            "run_id": _clean_text((frame_analysis.get("run_dir") or Path("")).name),
                            "capture_id": _clean_text(frame_analysis.get("capture_id")),
                            "capture_index": frame_analysis.get("capture_index"),
                            "delay_us": int(frame_analysis["delay_us"]),
                            "delay_from_emergence_us": int(frame_analysis["delay_from_emergence_us"]),
                            "component_kind": str(component_kind),
                            "component_id": str(component_id),
                            "move_direction": str(move_direction),
                            "y_px": int(y_px),
                            "side": str(side),
                            "current_x_px": int(current_x_px),
                            "sample_offset_px": int(offset_px),
                            "sample_x_px": int(sample_x_px),
                            "sample_in_bounds": bool(sample_in_bounds),
                            "contiguous_to_component_mask": bool(contiguous_to_component_mask),
                            "contiguous_to_attached_mask": bool(contiguous_to_component_mask),
                            "sample_is_included": bool(sample_is_included),
                            "sample_is_excluded": bool(sample_is_excluded),
                            "intermediate_pixels_all_included": bool(
                                intermediate_pixels_all_included
                            ),
                            "intermediate_pixels_all_excluded": bool(
                                intermediate_pixels_all_excluded
                            ),
                            "intermediate_included_count": int(intermediate_included_count),
                            "intermediate_excluded_count": int(intermediate_excluded_count),
                            "threshold_value": threshold_value,
                            "gray_edge": gray_edge,
                            "gray_sample": gray_sample,
                            "gray_headroom": gray_headroom,
                            "edge_gray_margin": edge_gray_margin,
                            "sample_gray_drop": sample_gray_drop,
                            "b_edge": None if edge_metrics is None else int(edge_metrics["b"]),
                            "g_edge": None if edge_metrics is None else int(edge_metrics["g"]),
                            "r_edge": None if edge_metrics is None else int(edge_metrics["r"]),
                            "b_sample": None if sample_metrics is None else int(sample_metrics["b"]),
                            "g_sample": None if sample_metrics is None else int(sample_metrics["g"]),
                            "r_sample": None if sample_metrics is None else int(sample_metrics["r"]),
                            "edge_bg_gap": None if edge_metrics is None else float(edge_metrics["bg_gap"]),
                            "sample_bg_gap": None if sample_metrics is None else float(sample_metrics["bg_gap"]),
                            "edge_gr_gap": None if edge_metrics is None else float(edge_metrics["gr_gap"]),
                            "sample_gr_gap": None if sample_metrics is None else float(sample_metrics["gr_gap"]),
                            "edge_br_gap": None if edge_metrics is None else float(edge_metrics["br_gap"]),
                            "sample_br_gap": None if sample_metrics is None else float(sample_metrics["br_gap"]),
                            "edge_rb_chroma": None if edge_metrics is None else float(edge_metrics["rb_chroma"]),
                            "sample_rb_chroma": None if sample_metrics is None else float(sample_metrics["rb_chroma"]),
                            "edge_blue_excess": None if edge_metrics is None else float(edge_metrics["blue_excess"]),
                            "sample_blue_excess": None if sample_metrics is None else float(sample_metrics["blue_excess"]),
                            "edge_lab_a": None if edge_metrics is None else float(edge_metrics["lab_a"]),
                            "edge_lab_b": None if edge_metrics is None else float(edge_metrics["lab_b"]),
                            "edge_lab_chroma": None if edge_metrics is None else float(edge_metrics["lab_chroma"]),
                            "sample_lab_a": None if sample_metrics is None else float(sample_metrics["lab_a"]),
                            "sample_lab_b": None if sample_metrics is None else float(sample_metrics["lab_b"]),
                            "sample_lab_chroma": None if sample_metrics is None else float(sample_metrics["lab_chroma"]),
                            "delta_lab_chroma": delta_lab_chroma,
                        }
                    )
    return features


def _extract_row_side_offset_features(frame_analysis: dict, *, max_offset_px: int) -> list[dict]:
    return _extract_component_row_side_offset_features(
        frame_analysis,
        component_kind="attached",
        component_id="attached_primary",
        component_mask=frame_analysis.get("attached_mask"),
        edge_rows=list(frame_analysis.get("attached_edge_rows") or []),
        move_directions=("outward",),
        max_offset_px=int(max_offset_px),
    )


def _frame_summary_row(
    frame_row: dict,
    frame_analysis: dict,
    *,
    feature_row_count: int,
) -> dict:
    record = dict(frame_row or {})
    image_ref = dict(record.get("image_ref") or {})
    return {
        "run_id": _clean_text((frame_analysis.get("run_dir") or Path("")).name),
        "capture_id": _clean_text(frame_analysis.get("capture_id")) or _clean_text(image_ref.get("capture_id")),
        "capture_index": frame_analysis.get("capture_index"),
        "phase": _clean_text(record.get("phase")),
        "status": _clean_text(record.get("status")),
        "delay_us": int(frame_analysis["delay_us"]),
        "delay_from_emergence_us": int(frame_analysis["delay_from_emergence_us"]),
        "image_relpath": _clean_text(image_ref.get("image_relpath")) or str(frame_analysis["image_path"]),
        "threshold_value": frame_analysis.get("threshold_value"),
        "attached_edge_row_count": int(len(frame_analysis.get("attached_edge_rows") or [])),
        "detached_component_count": int(len(frame_analysis.get("detached_components") or [])),
        "feature_row_count": int(feature_row_count),
        "current_attached_volume_nl": float(frame_analysis.get("current_attached_volume_nl") or 0.0),
        "current_total_visible_volume_nl": float(frame_analysis.get("current_total_visible_volume_nl") or 0.0),
        "detached_visible_volume_nl": float(frame_analysis.get("detached_visible_volume_nl") or 0.0),
        "roi_x0": int(frame_analysis["roi"]["x0"]),
        "roi_y0": int(frame_analysis["roi"]["y0"]),
        "roi_x1": int(frame_analysis["roi"]["x1"]),
        "roi_y1": int(frame_analysis["roi"]["y1"]),
    }


def _baseline_edge_rows(frame_analysis: dict) -> list[dict]:
    rows = []
    rows.extend(
        _component_baseline_edge_rows(
            frame_analysis,
            component_kind="attached",
            component_id="attached_primary",
            edge_rows=list(frame_analysis.get("attached_edge_rows") or []),
        )
    )
    for index, component in enumerate(list(frame_analysis.get("detached_components") or []), start=1):
        component_id = _clean_text(dict(component).get("component_id")) or f"detached_{index:02d}"
        rows.extend(
            _component_baseline_edge_rows(
                frame_analysis,
                component_kind="detached",
                component_id=str(component_id),
                edge_rows=list(dict(component).get("edge_rows") or []),
            )
        )
    return rows


def _run_cache_payload(
    experiment_root: Path,
    metadata_row: dict,
    *,
    max_offset_px: int,
    correction_cache: dict | None = None,
) -> dict:
    run_dir = report_mod._run_dir_for_row(experiment_root, metadata_row)
    plan_snapshot = report_mod._load_json(run_dir / "plan_snapshot.json")
    frame_rows = report_mod._iter_jsonl(run_dir / "frames.jsonl")
    correction_context = report_mod._resolve_online_stream_correction_context(
        experiment_root,
        run_dir,
        plan_snapshot=plan_snapshot,
        correction_cache=correction_cache,
    )
    analysis_config = plan_snapshot.get("analysis_config")

    frame_summaries = []
    edge_rows = []
    offset_features = []
    for row in list(frame_rows or []):
        record = dict(row or {})
        image_ref = dict(record.get("image_ref") or {})
        image_relpath = _clean_text(image_ref.get("image_relpath")) or _clean_text(record.get("image_relpath"))
        delay_us = _int_or_none(record.get("delay_us"))
        if delay_us is None:
            delay_us = _int_or_none(record.get("flash_delay_us"))
        if image_relpath is None or delay_us is None:
            continue
        capture_index = _int_or_none(record.get("capture_index"))
        if capture_index is None:
            capture_index = _int_or_none(image_ref.get("capture_index"))
        capture_id = _clean_text(record.get("capture_id")) or _clean_text(image_ref.get("capture_id"))
        frame_analysis = proto_mod._frame_analysis_from_capture(
            image_path=run_dir / str(image_relpath),
            nozzle_center_px=list(correction_context["nozzle_center_px"]),
            delay_us=int(delay_us),
            emergence_time_us=int(correction_context["emergence_time_us"]),
            analysis_config=analysis_config,
            capture_id=capture_id,
            capture_index=capture_index,
            run_key=str(metadata_row.get("Dataset name") or ""),
            run_label=str(metadata_row.get("Dataset name") or ""),
            run_dir=run_dir,
        )
        offset_rows = _extract_component_row_side_offset_features(
            frame_analysis,
            component_kind="attached",
            component_id="attached_primary",
            component_mask=frame_analysis.get("attached_mask"),
            edge_rows=list(frame_analysis.get("attached_edge_rows") or []),
            move_directions=("outward",),
            max_offset_px=int(max_offset_px),
        )
        for index, component in enumerate(list(frame_analysis.get("detached_components") or []), start=1):
            component_record = dict(component or {})
            component_id = _clean_text(component_record.get("component_id")) or f"detached_{index:02d}"
            offset_rows.extend(
                _extract_component_row_side_offset_features(
                    frame_analysis,
                    component_kind="detached",
                    component_id=str(component_id),
                    component_mask=component_record.get("final_mask"),
                    edge_rows=list(component_record.get("edge_rows") or []),
                    move_directions=("outward", "inward"),
                    max_offset_px=int(max_offset_px),
                )
            )
        frame_summaries.append(
            _frame_summary_row(
                record,
                frame_analysis,
                feature_row_count=len(offset_rows),
            )
        )
        edge_rows.extend(_baseline_edge_rows(frame_analysis))
        offset_features.extend(offset_rows)

    return {
        "run_id": str(metadata_row.get("Dataset name") or run_dir.name),
        "run_dir": str(run_dir),
        "print_pressure": _float_or_none(metadata_row.get("Print Pressure")),
        "print_pw_us": _int_or_none(metadata_row.get("Print PW")),
        "replicate_index": _int_or_none(metadata_row.get("Rep")),
        "mass_per_print_mg": _float_or_none(metadata_row.get("Mass/print")),
        "max_offset_px": int(max_offset_px),
        "correction_context": correction_context,
        "frame_summaries": frame_summaries,
        "baseline_edge_rows": edge_rows,
        "offset_features": offset_features,
    }


def export_online_chroma_edge_offset_cache(
    experiment_root: str | Path,
    *,
    print_pressure: float | int = DEFAULT_PRINT_PRESSURE,
    print_pw_us: int | None = None,
    run_id: str | None = None,
    max_offset_px: int = DEFAULT_MAX_OFFSET_PX,
    output_root: str | Path | None = None,
) -> dict:
    experiment_root = dataset_mod.resolve_experiment_root(experiment_root)
    max_offset_px = max(1, int(max_offset_px))
    metadata_rows = _matching_metadata_rows(
        experiment_root,
        print_pressure=print_pressure,
        print_pw_us=print_pw_us,
        run_id=run_id,
    )
    if not metadata_rows:
        raise ValueError(
            f"No {report_mod.PROCESS_NAME} metadata rows found under {experiment_root}"
            + (f" for print_pressure={print_pressure!r}" if print_pressure is not None else "")
            + (f", print_pw_us={print_pw_us!r}" if print_pw_us is not None else "")
            + (f", run_id={run_id!r}" if run_id is not None else "")
        )

    stage_dir = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else _default_output_root(
            experiment_root,
            print_pressure=print_pressure,
            max_offset_px=max_offset_px,
        )
    )
    stage_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = stage_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    correction_cache = {}
    run_summaries = []
    run_entries = []
    total_frame_count = 0
    total_edge_row_count = 0
    total_feature_row_count = 0
    started = time.perf_counter()
    for metadata_row in list(metadata_rows):
        run_started = time.perf_counter()
        payload = _run_cache_payload(
            experiment_root,
            metadata_row,
            max_offset_px=max_offset_px,
            correction_cache=correction_cache,
        )
        elapsed_s = float(time.perf_counter() - run_started)
        run_slug = _safe_slug(payload["run_id"])
        run_output_dir = runs_dir / run_slug
        run_output_dir.mkdir(parents=True, exist_ok=True)

        frame_summary_path = proto_mod._write_csv(run_output_dir / "frame_summary.csv", payload["frame_summaries"])
        edge_rows_path = proto_mod._write_csv(run_output_dir / "baseline_edge_rows.csv", payload["baseline_edge_rows"])
        offset_features_path = proto_mod._write_csv(run_output_dir / "row_side_offset_features.csv", payload["offset_features"])
        run_manifest = {
            "run_id": payload["run_id"],
            "run_dir": payload["run_dir"],
            "print_pressure": payload["print_pressure"],
            "print_pw_us": payload["print_pw_us"],
            "replicate_index": payload["replicate_index"],
            "mass_per_print_mg": payload["mass_per_print_mg"],
            "max_offset_px": payload["max_offset_px"],
            "elapsed_s": elapsed_s,
            "correction_context": payload["correction_context"],
            "frame_count": len(payload["frame_summaries"]),
            "edge_row_count": len(payload["baseline_edge_rows"]),
            "feature_row_count": len(payload["offset_features"]),
            "paths": {
                "frame_summary_csv": str(frame_summary_path),
                "baseline_edge_rows_csv": str(edge_rows_path),
                "row_side_offset_features_csv": str(offset_features_path),
            },
        }
        run_manifest_path = proto_mod._write_json(run_output_dir / "run_manifest.json", run_manifest)
        run_entries.append(run_manifest | {"run_manifest_json": str(run_manifest_path)})
        run_summaries.append(
            {
                "run_id": payload["run_id"],
                "print_pressure": payload["print_pressure"],
                "print_pw_us": payload["print_pw_us"],
                "replicate_index": payload["replicate_index"],
                "mass_per_print_mg": payload["mass_per_print_mg"],
                "frame_count": len(payload["frame_summaries"]),
                "edge_row_count": len(payload["baseline_edge_rows"]),
                "feature_row_count": len(payload["offset_features"]),
                "elapsed_s": elapsed_s,
                "frame_summary_csv": str(frame_summary_path),
                "baseline_edge_rows_csv": str(edge_rows_path),
                "row_side_offset_features_csv": str(offset_features_path),
            }
        )
        total_frame_count += int(len(payload["frame_summaries"]))
        total_edge_row_count += int(len(payload["baseline_edge_rows"]))
        total_feature_row_count += int(len(payload["offset_features"]))

    total_elapsed_s = float(time.perf_counter() - started)
    run_summary_csv = proto_mod._write_csv(stage_dir / "run_summary.csv", run_summaries)
    manifest = {
        "analysis": "online_chroma_edge_offset_cache",
        "experiment_root": str(experiment_root),
        "output_root": str(stage_dir),
        "print_pressure": _float_or_none(print_pressure),
        "print_pw_us": _int_or_none(print_pw_us),
        "run_id_filter": _clean_text(run_id),
        "max_offset_px": int(max_offset_px),
        "selected_rule_reference": dict(proto_mod.SELECTED_V2_RULE),
        "run_count": len(run_entries),
        "frame_count": int(total_frame_count),
        "edge_row_count": int(total_edge_row_count),
        "feature_row_count": int(total_feature_row_count),
        "elapsed_s": float(total_elapsed_s),
        "paths": {
            "run_summary_csv": str(run_summary_csv),
            "runs_dir": str(runs_dir),
        },
        "runs": run_entries,
    }
    manifest_path = proto_mod._write_json(stage_dir / "cache_manifest.json", manifest)
    return {
        **manifest,
        "cache_manifest_json": str(manifest_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export per-offset (+N px) chroma edge feature caches for archived online stream runs."
    )
    parser.add_argument(
        "--experiment-root",
        required=True,
        help="Experiment directory, metadata CSV, calibration_recordings dir, process dir, or run dir.",
    )
    parser.add_argument(
        "--print-pressure",
        type=float,
        default=float(DEFAULT_PRINT_PRESSURE),
        help="Filter online-stream metadata rows by print pressure. Defaults to 1.0.",
    )
    parser.add_argument(
        "--print-pw-us",
        type=int,
        default=None,
        help="Optional print pulse-width filter.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional Dataset name filter to export a cache for a single run.",
    )
    parser.add_argument(
        "--max-offset-px",
        type=int,
        default=int(DEFAULT_MAX_OFFSET_PX),
        help="Maximum outward offset to cache per row-side. Defaults to 3.",
    )
    parser.add_argument(
        "--output-root",
        default="",
        help="Optional output directory. Defaults to <experiment>/analysis/online_chroma_edge_offset_cache_...",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = export_online_chroma_edge_offset_cache(
        args.experiment_root,
        print_pressure=args.print_pressure,
        print_pw_us=args.print_pw_us,
        run_id=args.run_id,
        max_offset_px=args.max_offset_px,
        output_root=args.output_root or None,
    )
    print(
        json.dumps(
            {
                "output_root": payload["output_root"],
                "cache_manifest_json": payload["cache_manifest_json"],
                "run_count": payload["run_count"],
                "feature_row_count": payload["feature_row_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
