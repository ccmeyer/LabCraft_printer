from __future__ import annotations

import csv
import json
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis.dataset import (
    ANALYSIS_DIRNAME,
    STAGE_DIRNAME,
    _clean_text,
    _int_or_none,
    _json_cell,
    _preferred_columns,
    _write_csv,
    _write_json,
    build_stage0_inventory,
    default_output_root,
)


BASELINE_STAGE_DIRNAME = "stage_01_baseline"

FRAME_METRIC_COLUMNS = [
    "run_id",
    "capture_id",
    "capture_index",
    "image_relpath",
    "image_exists",
    "captured_at_utc",
    "flash_delay_us",
    "delay_from_emergence_us",
    "threshold_method",
    "threshold_value",
    "roi_x0",
    "roi_y0",
    "roi_x1",
    "roi_y1",
    "roi_width",
    "roi_height",
    "corridor_x0",
    "corridor_x1",
    "corridor_width",
    "dark_pixel_count",
    "dark_fraction",
    "component_count",
    "largest_component_area_px",
    "largest_component_bbox_x",
    "largest_component_bbox_y",
    "largest_component_bbox_w",
    "largest_component_bbox_h",
    "largest_component_centroid_x",
    "largest_component_centroid_y",
    "sample_frame",
]


def _load_gray_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Could not load grayscale image: {path}")
    return image


def _roi_bounds(image_shape, *, roi_width_frac: float, roi_top_frac: float, roi_bottom_frac: float):
    height, width = image_shape[:2]
    half_width = int(round(width * roi_width_frac / 2.0))
    center_x = width // 2
    x0 = max(0, center_x - half_width)
    x1 = min(width, center_x + half_width)
    y0 = max(0, min(height - 1, int(round(height * roi_top_frac))))
    y1 = max(y0 + 1, min(height, int(round(height * roi_bottom_frac))))
    return {
        "x0": int(x0),
        "y0": int(y0),
        "x1": int(x1),
        "y1": int(y1),
        "width": int(x1 - x0),
        "height": int(y1 - y0),
    }


def _threshold_roi(roi_gray: np.ndarray):
    threshold_value, mask = cv2.threshold(
        roi_gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )
    return float(threshold_value), mask


def _corridor_bounds(roi_shape, *, corridor_width_frac: float):
    height, width = roi_shape[:2]
    half_width = int(round(width * corridor_width_frac / 2.0))
    center_x = width // 2
    x0 = max(0, center_x - half_width)
    x1 = min(width, center_x + half_width)
    return {
        "x0": int(x0),
        "x1": int(x1),
        "width": int(x1 - x0),
    }


def _apply_corridor_mask(mask: np.ndarray, corridor: dict):
    trimmed = np.zeros_like(mask)
    trimmed[:, corridor["x0"] : corridor["x1"]] = mask[:, corridor["x0"] : corridor["x1"]]
    return trimmed


def _component_metrics(mask: np.ndarray):
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    component_count = max(0, int(count - 1))
    if component_count <= 0:
        return {
            "component_count": 0,
            "largest_component_area_px": 0,
            "largest_component_bbox_x": None,
            "largest_component_bbox_y": None,
            "largest_component_bbox_w": None,
            "largest_component_bbox_h": None,
            "largest_component_centroid_x": None,
            "largest_component_centroid_y": None,
        }

    foreground_stats = stats[1:]
    largest_index = int(np.argmax(foreground_stats[:, cv2.CC_STAT_AREA])) + 1
    largest_stats = stats[largest_index]
    largest_centroid = centroids[largest_index]
    return {
        "component_count": component_count,
        "largest_component_area_px": int(largest_stats[cv2.CC_STAT_AREA]),
        "largest_component_bbox_x": int(largest_stats[cv2.CC_STAT_LEFT]),
        "largest_component_bbox_y": int(largest_stats[cv2.CC_STAT_TOP]),
        "largest_component_bbox_w": int(largest_stats[cv2.CC_STAT_WIDTH]),
        "largest_component_bbox_h": int(largest_stats[cv2.CC_STAT_HEIGHT]),
        "largest_component_centroid_x": float(largest_centroid[0]),
        "largest_component_centroid_y": float(largest_centroid[1]),
    }


def _mask_overlay(roi_gray: np.ndarray, mask: np.ndarray, component_metrics: dict):
    overlay = cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR)
    overlay[mask > 0] = (0, 0, 255)
    alpha = 0.35
    blended = cv2.addWeighted(cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR), 1.0 - alpha, overlay, alpha, 0.0)

    if component_metrics.get("largest_component_bbox_w"):
        x = int(component_metrics["largest_component_bbox_x"])
        y = int(component_metrics["largest_component_bbox_y"])
        w = int(component_metrics["largest_component_bbox_w"])
        h = int(component_metrics["largest_component_bbox_h"])
        cv2.rectangle(blended, (x, y), (x + w, y + h), (0, 255, 255), 2)

    return blended


def _resize_to_height(image: np.ndarray, target_height: int) -> np.ndarray:
    height, width = image.shape[:2]
    scale = float(target_height) / float(height)
    target_width = max(1, int(round(width * scale)))
    return cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _draw_label(image: np.ndarray, text: str):
    cv2.putText(
        image,
        text,
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def _build_sample_panel(gray: np.ndarray, roi: dict, corridor: dict, roi_mask: np.ndarray, metric_row: dict):
    full = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(full, (roi["x0"], roi["y0"]), (roi["x1"], roi["y1"]), (0, 255, 255), 3)
    full = _draw_label(
        full,
        (
            f"frame {metric_row['capture_index']}  delay={metric_row.get('flash_delay_us')} us  "
            f"thr={int(round(metric_row['threshold_value']))}"
        ),
    )

    roi_gray = gray[roi["y0"] : roi["y1"], roi["x0"] : roi["x1"]]
    roi_gray_bgr = cv2.cvtColor(roi_gray, cv2.COLOR_GRAY2BGR)
    x0 = max(0, min(roi_gray_bgr.shape[1] - 1, corridor["x0"]))
    x1 = max(0, min(roi_gray_bgr.shape[1] - 1, corridor["x1"] - 1))
    cv2.line(roi_gray_bgr, (x0, 0), (x0, roi_gray_bgr.shape[0] - 1), (0, 255, 255), 2)
    cv2.line(roi_gray_bgr, (x1, 0), (x1, roi_gray_bgr.shape[0] - 1), (0, 255, 255), 2)
    roi_gray_bgr = _draw_label(roi_gray_bgr, "grayscale ROI")

    overlay = _mask_overlay(roi_gray, roi_mask, metric_row)
    overlay = _draw_label(
        overlay,
        (
            f"mask  dark={metric_row['dark_fraction']:.3f}  "
            f"largest={metric_row['largest_component_area_px']}"
        ),
    )

    target_height = 320
    row_images = [
        _resize_to_height(full, target_height),
        _resize_to_height(roi_gray_bgr, target_height),
        _resize_to_height(overlay, target_height),
    ]
    return cv2.hconcat(row_images)


def _sample_indices(frame_count: int, *, sample_count: int, extra_frame_indices: list[int] | None = None):
    indices = set()
    if frame_count <= 0:
        return []
    if sample_count > 0:
        raw = np.linspace(1, frame_count, num=sample_count)
        indices.update(int(round(float(value))) for value in raw)
    for value in extra_frame_indices or []:
        if 1 <= int(value) <= frame_count:
            indices.add(int(value))
    return sorted(indices)


def _frame_metric_row(
    run_id: str,
    frame_row: dict,
    roi: dict,
    corridor: dict,
    threshold_value: float,
    mask: np.ndarray,
):
    metrics = _component_metrics(mask)
    dark_pixel_count = int(np.count_nonzero(mask))
    dark_fraction = float(dark_pixel_count) / float(mask.size) if mask.size else 0.0
    return {
        "run_id": run_id,
        "capture_id": frame_row.get("capture_id"),
        "capture_index": _int_or_none(frame_row.get("capture_index")),
        "image_relpath": frame_row.get("image_relpath"),
        "image_exists": bool(frame_row.get("image_exists")),
        "captured_at_utc": frame_row.get("captured_at_utc"),
        "flash_delay_us": _int_or_none(frame_row.get("flash_delay_us")),
        "delay_from_emergence_us": _int_or_none(frame_row.get("delay_from_emergence_us")),
        "threshold_method": "otsu_dark",
        "threshold_value": float(threshold_value),
        "roi_x0": roi["x0"],
        "roi_y0": roi["y0"],
        "roi_x1": roi["x1"],
        "roi_y1": roi["y1"],
        "roi_width": roi["width"],
        "roi_height": roi["height"],
        "corridor_x0": corridor["x0"],
        "corridor_x1": corridor["x1"],
        "corridor_width": corridor["width"],
        "dark_pixel_count": dark_pixel_count,
        "dark_fraction": dark_fraction,
        **metrics,
        "sample_frame": False,
    }


def _summary_from_metric_rows(metric_rows: list[dict]):
    thresholds = [row["threshold_value"] for row in metric_rows]
    dark_fracs = [row["dark_fraction"] for row in metric_rows]
    largest_areas = [row["largest_component_area_px"] for row in metric_rows]
    return {
        "frame_count": len(metric_rows),
        "threshold_min": min(thresholds) if thresholds else None,
        "threshold_max": max(thresholds) if thresholds else None,
        "dark_fraction_min": min(dark_fracs) if dark_fracs else None,
        "dark_fraction_max": max(dark_fracs) if dark_fracs else None,
        "largest_component_area_min": min(largest_areas) if largest_areas else None,
        "largest_component_area_max": max(largest_areas) if largest_areas else None,
    }


def export_stage1_baseline(
    experiment_root: str | Path,
    *,
    output_root: str | Path | None = None,
    run_ids: list[str] | None = None,
    limit_runs: int | None = None,
    include_unmatched: bool = False,
    sample_count: int = 6,
    extra_frame_indices: list[int] | None = None,
    roi_width_frac: float = 0.35,
    roi_top_frac: float = 0.10,
    roi_bottom_frac: float = 1.0,
    corridor_width_frac: float = 0.70,
):
    inventory = build_stage0_inventory(
        experiment_root,
        include_unmatched=include_unmatched,
        run_ids=run_ids,
        limit_runs=limit_runs,
    )

    output_path = Path(output_root).expanduser().resolve() if output_root else default_output_root(experiment_root)
    output_path.mkdir(parents=True, exist_ok=True)

    run_manifests = []
    for run_row in inventory["selected_runs"]:
        run_id = str(run_row["run_id"])
        stage_dir = output_path / "runs" / run_id / BASELINE_STAGE_DIRNAME
        frame_rows = list(inventory["frames_by_run_id"][run_id])
        if not frame_rows:
            raise ValueError(f"No frame index rows available for run: {run_id}")

        sample_indices = _sample_indices(
            len(frame_rows),
            sample_count=sample_count,
            extra_frame_indices=extra_frame_indices,
        )

        metric_rows = []
        sample_panels = []
        sample_panel_paths = []

        for frame_row in frame_rows:
            image_path = Path(str(frame_row["image_abs_path"]))
            gray = _load_gray_image(image_path)
            roi = _roi_bounds(
                gray.shape,
                roi_width_frac=roi_width_frac,
                roi_top_frac=roi_top_frac,
                roi_bottom_frac=roi_bottom_frac,
            )
            roi_gray = gray[roi["y0"] : roi["y1"], roi["x0"] : roi["x1"]]
            threshold_value, roi_mask_raw = _threshold_roi(roi_gray)
            corridor = _corridor_bounds(roi_gray.shape, corridor_width_frac=corridor_width_frac)
            roi_mask = _apply_corridor_mask(roi_mask_raw, corridor)
            metric_row = _frame_metric_row(run_id, frame_row, roi, corridor, threshold_value, roi_mask)
            if metric_row["capture_index"] in sample_indices:
                metric_row["sample_frame"] = True
                panel = _build_sample_panel(gray, roi, corridor, roi_mask, metric_row)
                panel_path = stage_dir / "samples" / f"frame_{metric_row['capture_index']:03d}_panel.png"
                panel_path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(panel_path), panel)
                sample_panel_paths.append(str(panel_path))
                sample_panels.append(panel)
            metric_rows.append(metric_row)

        frame_metrics_csv = stage_dir / "frame_metrics.csv"
        summary_json = stage_dir / "baseline_manifest.json"
        contact_sheet_png = stage_dir / "sample_contact_sheet.png"

        _write_csv(frame_metrics_csv, _preferred_columns(metric_rows, FRAME_METRIC_COLUMNS), metric_rows)
        if sample_panels:
            contact_sheet = cv2.vconcat(sample_panels)
            contact_sheet_png.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(contact_sheet_png), contact_sheet)

        summary = {
            "schema_version": 1,
            "stage": "baseline",
            "run_id": run_id,
            "run_dir": run_row["run_dir"],
            "roi": {
                "width_frac": float(roi_width_frac),
                "top_frac": float(roi_top_frac),
                "bottom_frac": float(roi_bottom_frac),
                "corridor_width_frac": float(corridor_width_frac),
                "bounds_px": {
                    "x0": metric_rows[0]["roi_x0"],
                    "y0": metric_rows[0]["roi_y0"],
                    "x1": metric_rows[0]["roi_x1"],
                    "y1": metric_rows[0]["roi_y1"],
                    "width": metric_rows[0]["roi_width"],
                    "height": metric_rows[0]["roi_height"],
                },
                "corridor_px": {
                    "x0": metric_rows[0]["corridor_x0"],
                    "x1": metric_rows[0]["corridor_x1"],
                    "width": metric_rows[0]["corridor_width"],
                },
            },
            "threshold_method": "otsu_dark",
            "sample_capture_indices": sample_indices,
            "sample_panel_paths": sample_panel_paths,
            "outputs": {
                "frame_metrics_csv": str(frame_metrics_csv),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
            },
            "summary": _summary_from_metric_rows(metric_rows),
        }
        _write_json(summary_json, summary)
        run_manifests.append(
            {
                "run_id": run_id,
                "run_dir": run_row["run_dir"],
                "frame_metrics_csv": str(frame_metrics_csv),
                "baseline_manifest_json": str(summary_json),
                "sample_contact_sheet_png": str(contact_sheet_png) if sample_panels else None,
                "frame_count": len(metric_rows),
                "sample_frame_count": len(sample_indices),
            }
        )

    manifest = {
        "schema_version": 1,
        "stage": "baseline",
        "experiment_root": inventory["experiment_root"],
        "output_root": str(output_path),
        "selected_run_count": len(run_manifests),
        "run_ids": [row["run_id"] for row in run_manifests],
        "roi_width_frac": float(roi_width_frac),
        "roi_top_frac": float(roi_top_frac),
        "roi_bottom_frac": float(roi_bottom_frac),
        "corridor_width_frac": float(corridor_width_frac),
        "sample_count": int(sample_count),
        "extra_frame_indices": list(extra_frame_indices or []),
        "runs": run_manifests,
    }
    manifest_path = output_path / "baseline_manifest.json"
    _write_json(manifest_path, manifest)
    manifest["manifest_path"] = str(manifest_path)
    return manifest
