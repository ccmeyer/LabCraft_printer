from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
FREERTOS_INTERFACE_DIR = REPO_ROOT / "FreeRTOS-interface"
if str(FREERTOS_INTERFACE_DIR) not in sys.path:
    sys.path.insert(0, str(FREERTOS_INTERFACE_DIR))

from tools.annotate_refuel_dataset import (
    load_jsonl,
    normalize_line,
    raw_line_to_display,
    validate_label_record,
)


GEOMETRY_KEYS = ("left_wall", "right_wall", "top_line", "bottom_line")
CHANNEL_X_ERROR_KEYS = (
    "channel_left_dx_px",
    "channel_right_dx_px",
    "channel_center_dx_px",
    "channel_width_error_px",
)
CONTACT_SHEET_CATEGORIES = (
    "worst_meniscus_errors",
    "status_mismatches",
    "per_scene_worst",
    "worst_channel_geometry_errors",
)
MISSING_LABEL_STATUS = "missing_label"
MISSING_PREDICTION_STATUS = "missing_prediction"

LABEL_GEOMETRY_COLOR_BGR = (255, 255, 0)
PREDICTED_GEOMETRY_COLOR_BGR = (0, 255, 255)
LABEL_MENISCUS_COLOR_BGR = (255, 0, 255)
PREDICTED_MENISCUS_COLOR_BGR = (0, 128, 255)
TEXT_COLOR_BGR = (245, 245, 245)
TEXT_BG_COLOR_BGR = (25, 25, 25)
DEFAULT_REFUEL_DEBUG_PARAMS = {
    "offset": 40,
    "width": 20,
    "threshold": 60,
    "prominence": 4,
    "empty_cutoff": 0.25,
    "bottom_guard_px": 2,
}


CSV_FIELDNAMES = [
    "prediction_source",
    "frame_id",
    "scene_id",
    "scene_tags",
    "capture_index",
    "image_relpath",
    "rejected",
    "label_status",
    "predicted_status",
    "status_match",
    "label_meniscus_y_px",
    "predicted_meniscus_y_px",
    "meniscus_y_error_px",
    "meniscus_abs_error_px",
    "label_level_from_bottom_px",
    "predicted_level_from_bottom_px",
    "level_error_px",
    "level_abs_error_px",
    "left_wall_midpoint_error_px",
    "right_wall_midpoint_error_px",
    "top_line_midpoint_error_px",
    "bottom_line_midpoint_error_px",
    "label_channel_left_x_px",
    "label_channel_right_x_px",
    "label_channel_center_x_px",
    "label_channel_width_px",
    "predicted_channel_left_x_px",
    "predicted_channel_right_x_px",
    "predicted_channel_center_x_px",
    "predicted_channel_width_px",
    "channel_left_dx_px",
    "channel_right_dx_px",
    "channel_center_dx_px",
    "channel_center_abs_error_px",
    "channel_width_error_px",
    "channel_width_abs_error_px",
]


def _mean(values):
    values = [float(value) for value in values]
    if not values:
        return None
    return float(sum(values) / len(values))


def _median(values):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return float(values[mid])
    return float((values[mid - 1] + values[mid]) / 2.0)


def _nearest_rank_percentile(values, percentile):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    idx = int(math.ceil((float(percentile) / 100.0) * len(values))) - 1
    idx = max(0, min(len(values) - 1, idx))
    return float(values[idx])


def _rmse(values):
    values = [float(value) for value in values]
    if not values:
        return None
    return float(math.sqrt(sum(value * value for value in values) / len(values)))


def _line_display_mean_y(line, raw_shape):
    display_line = raw_line_to_display(line, raw_shape)
    if display_line is None:
        return None
    return float((display_line[0][1] + display_line[1][1]) / 2.0)


def _line_display_midpoint(line, raw_shape):
    display_line = raw_line_to_display(line, raw_shape)
    if display_line is None:
        return None
    return [
        float((display_line[0][0] + display_line[1][0]) / 2.0),
        float((display_line[0][1] + display_line[1][1]) / 2.0),
    ]


def _channel_x_measurement(geometry_midpoints):
    left = (geometry_midpoints or {}).get("left_wall")
    right = (geometry_midpoints or {}).get("right_wall")
    if left is None or right is None:
        return {
            "left_x_px": None,
            "right_x_px": None,
            "center_x_px": None,
            "width_px": None,
        }
    left_x = float(left[0])
    right_x = float(right[0])
    return {
        "left_x_px": left_x,
        "right_x_px": right_x,
        "center_x_px": float((left_x + right_x) / 2.0),
        "width_px": float(right_x - left_x),
    }


def _signed_error_summary(values):
    values = [float(value) for value in values if value is not None]
    summary = _numeric_summary(values)
    summary["mean_error"] = _mean(values)
    return summary


def _distance(point_a, point_b):
    if point_a is None or point_b is None:
        return None
    dx = float(point_b[0]) - float(point_a[0])
    dy = float(point_b[1]) - float(point_a[1])
    return float(math.hypot(dx, dy))


def _status_counts(rows, key):
    return dict(sorted(Counter(str(row.get(key) or "") for row in rows).items()))


def _latest_analysis_by_frame(analysis_rows):
    latest = {}
    for row in analysis_rows:
        frame_id = row.get("frame_id")
        if not frame_id:
            continue
        if not any(
            key in row
            for key in (
                "predicted_status",
                "predicted_channel_geometry",
                "predicted_meniscus_line",
            )
        ):
            continue
        latest[str(frame_id)] = row
    return latest


def _coerce_label_rows(labels):
    rows_by_frame = defaultdict(list)
    for label in labels:
        frame_id = label.get("frame_id")
        if frame_id:
            rows_by_frame[str(frame_id)].append(label)
    return rows_by_frame


def _frame_sort_key(frame):
    return (str(frame.get("scene_id") or ""), int(frame.get("capture_index") or 0), str(frame.get("frame_id") or ""))


def label_measurements(label, frame):
    raw_shape = frame.get("raw_image_shape")
    status = str(label.get("status") or MISSING_LABEL_STATUS)
    geometry = label.get("channel_geometry") or {}
    meniscus_line = label.get("meniscus_line")

    meniscus_y = None
    if status == "visible" and meniscus_line is not None:
        meniscus_y = _line_display_mean_y(meniscus_line, raw_shape)

    bottom_y = _line_display_mean_y(geometry.get("bottom_line"), raw_shape)
    level = None
    if meniscus_y is not None and bottom_y is not None:
        level = float(bottom_y - meniscus_y)

    geometry_midpoints = {}
    for key in GEOMETRY_KEYS:
        geometry_midpoints[key] = _line_display_midpoint(geometry.get(key), raw_shape)

    return {
        "status": status,
        "meniscus_y_px": meniscus_y,
        "bottom_y_px": bottom_y,
        "level_from_bottom_px": level,
        "geometry_midpoints": geometry_midpoints,
    }


def prediction_measurements(seed, frame):
    if seed is None:
        return {
            "status": MISSING_PREDICTION_STATUS,
            "meniscus_y_px": None,
            "bottom_y_px": None,
            "level_from_bottom_px": None,
            "geometry_midpoints": {key: None for key in GEOMETRY_KEYS},
        }

    raw_shape = frame.get("raw_image_shape")
    status = str(seed.get("predicted_status") or "not_found")
    geometry = seed.get("predicted_channel_geometry") or {}
    meniscus_line = seed.get("predicted_meniscus_line")

    meniscus_y = None
    if status == "visible" and meniscus_line is not None:
        meniscus_y = _line_display_mean_y(meniscus_line, raw_shape)

    bottom_y = _line_display_mean_y(geometry.get("bottom_line"), raw_shape)
    level = None
    if meniscus_y is not None and bottom_y is not None:
        level = float(bottom_y - meniscus_y)

    geometry_midpoints = {}
    for key in GEOMETRY_KEYS:
        geometry_midpoints[key] = _line_display_midpoint(geometry.get(key), raw_shape)

    return {
        "status": status,
        "meniscus_y_px": meniscus_y,
        "bottom_y_px": bottom_y,
        "level_from_bottom_px": level,
        "geometry_midpoints": geometry_midpoints,
    }


def load_refuel_evaluation_run(run_dir, include_rejected=False):
    run_dir = Path(run_dir).resolve()
    frames = load_jsonl(run_dir / "frames.jsonl")
    scenes = load_jsonl(run_dir / "scenes.jsonl")
    analysis_rows = load_jsonl(run_dir / "analysis.jsonl")
    labels = load_jsonl(run_dir / "labels.jsonl")

    scenes_by_id = {
        str(scene.get("scene_id")): scene for scene in scenes if scene.get("scene_id")
    }
    label_rows_by_frame = _coerce_label_rows(labels)
    analysis_by_frame = _latest_analysis_by_frame(analysis_rows)

    warnings = []
    validation_errors = []
    duplicate_labels = {
        frame_id: len(rows)
        for frame_id, rows in label_rows_by_frame.items()
        if len(rows) > 1
    }
    if duplicate_labels:
        warnings.append(f"duplicate labels for {len(duplicate_labels)} frame(s)")

    missing_frame_metadata = []
    evaluated_frames = []
    skipped_rejected = 0
    for frame in sorted(frames, key=_frame_sort_key):
        frame_id = str(frame.get("frame_id") or "")
        if not frame_id:
            missing_frame_metadata.append("<blank frame_id>")
            continue
        if not frame.get("raw_image_shape"):
            missing_frame_metadata.append(frame_id)
        if bool(frame.get("rejected")) and not include_rejected:
            skipped_rejected += 1
            continue
        evaluated_frames.append(frame)

    if missing_frame_metadata:
        warnings.append(f"missing frame metadata for {len(missing_frame_metadata)} frame(s)")
    if skipped_rejected:
        warnings.append(f"skipped {skipped_rejected} rejected frame(s)")

    missing_labels = []
    for frame in evaluated_frames:
        frame_id = str(frame.get("frame_id") or "")
        labels_for_frame = label_rows_by_frame.get(frame_id, [])
        if not labels_for_frame:
            missing_labels.append(frame_id)
            continue
        label = labels_for_frame[-1]
        try:
            validate_label_record(label)
        except Exception as exc:
            validation_errors.append({"frame_id": frame_id, "error": str(exc)})

    if missing_labels:
        warnings.append(f"missing labels for {len(missing_labels)} evaluated frame(s)")
    if validation_errors:
        warnings.append(f"validation errors for {len(validation_errors)} label(s)")

    return {
        "run_dir": str(run_dir),
        "frames": frames,
        "scenes": scenes,
        "scenes_by_id": scenes_by_id,
        "analysis_rows": analysis_rows,
        "analysis_by_frame": analysis_by_frame,
        "labels": labels,
        "label_rows_by_frame": label_rows_by_frame,
        "evaluated_frames": evaluated_frames,
        "warnings": warnings,
        "missing_labels": missing_labels,
        "duplicate_labels": duplicate_labels,
        "validation_errors": validation_errors,
        "missing_frame_metadata": missing_frame_metadata,
        "skipped_rejected": skipped_rejected,
    }


def _numeric_summary(values):
    values = [float(value) for value in values if value is not None]
    return {
        "count": len(values),
        "mae": _mean(abs(value) for value in values),
        "median_abs_error": _median(abs(value) for value in values),
        "rmse": _rmse(values),
        "p90_abs_error": _nearest_rank_percentile([abs(value) for value in values], 90),
        "max_abs_error": max([abs(value) for value in values], default=None),
    }


def _scene_tags(scene):
    return [str(tag) for tag in (scene or {}).get("scene_tags") or []]


def _csv_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return value


def _frame_metric(frame, scene, label, seed, prediction_source="saved"):
    frame_id = str(frame.get("frame_id") or "")
    if label is None:
        label_measured = {
            "status": MISSING_LABEL_STATUS,
            "meniscus_y_px": None,
            "level_from_bottom_px": None,
            "geometry_midpoints": {key: None for key in GEOMETRY_KEYS},
        }
    else:
        label_measured = label_measurements(label, frame)
    pred_measured = prediction_measurements(seed, frame)

    label_status = label_measured["status"]
    predicted_status = pred_measured["status"]
    status_match = bool(label_status == predicted_status)

    meniscus_error = None
    if (
        label_status == "visible"
        and label_measured.get("meniscus_y_px") is not None
        and pred_measured.get("meniscus_y_px") is not None
    ):
        meniscus_error = float(pred_measured["meniscus_y_px"] - label_measured["meniscus_y_px"])

    level_error = None
    if (
        label_status == "visible"
        and label_measured.get("level_from_bottom_px") is not None
        and pred_measured.get("level_from_bottom_px") is not None
    ):
        level_error = float(pred_measured["level_from_bottom_px"] - label_measured["level_from_bottom_px"])

    row = {
        "prediction_source": str(prediction_source or "saved"),
        "frame_id": frame_id,
        "scene_id": str(frame.get("scene_id") or ""),
        "scene_tags": ";".join(_scene_tags(scene)),
        "capture_index": int(frame.get("capture_index") or 0),
        "image_relpath": str(frame.get("image_relpath") or ""),
        "rejected": bool(frame.get("rejected")),
        "label_status": label_status,
        "predicted_status": predicted_status,
        "status_match": status_match,
        "label_meniscus_y_px": label_measured.get("meniscus_y_px"),
        "predicted_meniscus_y_px": pred_measured.get("meniscus_y_px"),
        "meniscus_y_error_px": meniscus_error,
        "meniscus_abs_error_px": None if meniscus_error is None else abs(meniscus_error),
        "label_level_from_bottom_px": label_measured.get("level_from_bottom_px"),
        "predicted_level_from_bottom_px": pred_measured.get("level_from_bottom_px"),
        "level_error_px": level_error,
        "level_abs_error_px": None if level_error is None else abs(level_error),
    }

    label_midpoints = label_measured.get("geometry_midpoints") or {}
    pred_midpoints = pred_measured.get("geometry_midpoints") or {}
    for key in GEOMETRY_KEYS:
        row[f"{key}_midpoint_error_px"] = _distance(
            label_midpoints.get(key),
            pred_midpoints.get(key),
        )

    label_channel = _channel_x_measurement(label_midpoints)
    pred_channel = _channel_x_measurement(pred_midpoints)
    row.update(
        {
            "label_channel_left_x_px": label_channel["left_x_px"],
            "label_channel_right_x_px": label_channel["right_x_px"],
            "label_channel_center_x_px": label_channel["center_x_px"],
            "label_channel_width_px": label_channel["width_px"],
            "predicted_channel_left_x_px": pred_channel["left_x_px"],
            "predicted_channel_right_x_px": pred_channel["right_x_px"],
            "predicted_channel_center_x_px": pred_channel["center_x_px"],
            "predicted_channel_width_px": pred_channel["width_px"],
        }
    )
    channel_left_dx = None
    channel_right_dx = None
    channel_center_dx = None
    channel_width_error = None
    if label_channel["left_x_px"] is not None and pred_channel["left_x_px"] is not None:
        channel_left_dx = float(pred_channel["left_x_px"] - label_channel["left_x_px"])
    if label_channel["right_x_px"] is not None and pred_channel["right_x_px"] is not None:
        channel_right_dx = float(pred_channel["right_x_px"] - label_channel["right_x_px"])
    if label_channel["center_x_px"] is not None and pred_channel["center_x_px"] is not None:
        channel_center_dx = float(pred_channel["center_x_px"] - label_channel["center_x_px"])
    if label_channel["width_px"] is not None and pred_channel["width_px"] is not None:
        channel_width_error = float(pred_channel["width_px"] - label_channel["width_px"])
    row.update(
        {
            "channel_left_dx_px": channel_left_dx,
            "channel_right_dx_px": channel_right_dx,
            "channel_center_dx_px": channel_center_dx,
            "channel_center_abs_error_px": None if channel_center_dx is None else abs(channel_center_dx),
            "channel_width_error_px": channel_width_error,
            "channel_width_abs_error_px": None if channel_width_error is None else abs(channel_width_error),
        }
    )

    return row


def _build_confusion_matrix(frame_metrics):
    labels = sorted({row["label_status"] for row in frame_metrics})
    preds = sorted({row["predicted_status"] for row in frame_metrics})
    matrix = {}
    for label_status in labels:
        matrix[label_status] = {pred_status: 0 for pred_status in preds}
    for row in frame_metrics:
        matrix[row["label_status"]][row["predicted_status"]] += 1
    return matrix


def _status_accuracy(frame_metrics):
    if not frame_metrics:
        return None
    matches = sum(1 for row in frame_metrics if row.get("status_match"))
    return float(matches / len(frame_metrics))


def _scene_summaries(frame_metrics, scenes_by_id):
    rows_by_scene = defaultdict(list)
    for row in frame_metrics:
        rows_by_scene[row["scene_id"]].append(row)

    summaries = {}
    for scene_id, rows in sorted(rows_by_scene.items()):
        meniscus_errors = [
            row["meniscus_y_error_px"]
            for row in rows
            if row.get("meniscus_y_error_px") is not None
        ]
        level_errors = [
            row["level_error_px"]
            for row in rows
            if row.get("level_error_px") is not None
        ]
        channel_x_errors = {
            key: _signed_error_summary(row.get(key) for row in rows)
            for key in CHANNEL_X_ERROR_KEYS
        }
        summaries[scene_id] = {
            "scene_id": scene_id,
            "scene_tags": _scene_tags(scenes_by_id.get(scene_id)),
            "frame_count": len(rows),
            "label_status_counts": _status_counts(rows, "label_status"),
            "predicted_status_counts": _status_counts(rows, "predicted_status"),
            "status_accuracy": _status_accuracy(rows),
            "meniscus_y_error_px": _numeric_summary(meniscus_errors),
            "level_error_px": _numeric_summary(level_errors),
            "channel_x_error_px": channel_x_errors,
        }
    return summaries


def _single_source_result(loaded, prediction_source="saved"):
    prediction_source = str(prediction_source or "saved")
    frame_metrics = []
    warnings = list(loaded["warnings"])

    for frame in loaded["evaluated_frames"]:
        frame_id = str(frame.get("frame_id") or "")
        scene = loaded["scenes_by_id"].get(str(frame.get("scene_id") or ""))
        labels_for_frame = loaded["label_rows_by_frame"].get(frame_id, [])
        label = labels_for_frame[-1] if labels_for_frame else None
        saved_seed = loaded["analysis_by_frame"].get(frame_id)
        seed = saved_seed
        if prediction_source == "rerun":
            image_relpath = str(frame.get("image_relpath") or "")
            if not image_relpath:
                seed = None
                warnings.append(f"missing image_relpath for rerun frame {frame_id}")
            else:
                image_path = Path(loaded["run_dir"]) / image_relpath
                try:
                    cv2, _np = _import_overlay_deps()
                    raw_image = _read_overlay_image(cv2, image_path)
                    seed = rerun_refuel_detector_prediction(
                        raw_image,
                        _analysis_params_from_seed(saved_seed),
                    )["seed"]
                except Exception as exc:
                    seed = None
                    warnings.append(f"rerun prediction failed for {frame_id}: {exc}")
        frame_metrics.append(_frame_metric(frame, scene, label, seed, prediction_source=prediction_source))

    meniscus_errors = [
        row["meniscus_y_error_px"]
        for row in frame_metrics
        if row.get("meniscus_y_error_px") is not None
    ]
    level_errors = [
        row["level_error_px"]
        for row in frame_metrics
        if row.get("level_error_px") is not None
    ]
    geometry_error_summary = {}
    for key in GEOMETRY_KEYS:
        errors = [
            row[f"{key}_midpoint_error_px"]
            for row in frame_metrics
            if row.get(f"{key}_midpoint_error_px") is not None
        ]
        geometry_error_summary[key] = _numeric_summary(errors)
    channel_x_error_summary = {
        key: _signed_error_summary(row.get(key) for row in frame_metrics)
        for key in CHANNEL_X_ERROR_KEYS
    }

    summary = {
        "prediction_source": prediction_source,
        "run_dir": loaded["run_dir"],
        "frame_count": len(loaded["frames"]),
        "evaluated_frame_count": len(frame_metrics),
        "scene_count": len(loaded["scenes"]),
        "analysis_seed_count": len(loaded["analysis_by_frame"]),
        "label_count": len(loaded["labels"]),
        "skipped_rejected_count": loaded["skipped_rejected"],
        "missing_label_count": len(loaded["missing_labels"]),
        "duplicate_label_frame_count": len(loaded["duplicate_labels"]),
        "validation_error_count": len(loaded["validation_errors"]),
        "missing_frame_metadata_count": len(loaded["missing_frame_metadata"]),
        "status_accuracy": _status_accuracy(frame_metrics),
        "label_status_counts": _status_counts(frame_metrics, "label_status"),
        "predicted_status_counts": _status_counts(frame_metrics, "predicted_status"),
        "meniscus_y_error_px": _numeric_summary(meniscus_errors),
        "level_error_px": _numeric_summary(level_errors),
        "geometry_midpoint_error_px": geometry_error_summary,
        "channel_x_error_px": channel_x_error_summary,
    }

    result = {
        "summary": summary,
        "warnings": warnings,
        "strict_failures": {
            "missing_labels": loaded["missing_labels"],
            "duplicate_labels": loaded["duplicate_labels"],
            "validation_errors": loaded["validation_errors"],
            "missing_frame_metadata": loaded["missing_frame_metadata"],
        },
        "confusion_matrix": _build_confusion_matrix(frame_metrics),
        "scenes": _scene_summaries(frame_metrics, loaded["scenes_by_id"]),
        "frame_metrics": frame_metrics,
    }
    return result


def evaluate_refuel_run(run_dir, include_rejected=False, prediction_source="saved"):
    prediction_source = str(prediction_source or "saved")
    if prediction_source not in ("saved", "rerun", "both"):
        raise ValueError("prediction_source must be one of: saved, rerun, both")

    if prediction_source == "both":
        return {
            "prediction_source": "both",
            "sources": {
                "saved": evaluate_refuel_run(
                    run_dir,
                    include_rejected=include_rejected,
                    prediction_source="saved",
                ),
                "rerun": evaluate_refuel_run(
                    run_dir,
                    include_rejected=include_rejected,
                    prediction_source="rerun",
                ),
            },
        }

    loaded = load_refuel_evaluation_run(run_dir, include_rejected=include_rejected)
    return _single_source_result(loaded, prediction_source=prediction_source)


def _worst_frames(frame_metrics, worst_count):
    candidates = [
        row
        for row in frame_metrics
        if row.get("meniscus_abs_error_px") is not None
    ]
    candidates.sort(
        key=lambda row: (
            -float(row["meniscus_abs_error_px"]),
            row.get("scene_id") or "",
            int(row.get("capture_index") or 0),
        )
    )
    return candidates[: max(0, int(worst_count))]


def _worst_channel_geometry_frames(frame_metrics, worst_count):
    candidates = [
        row
        for row in frame_metrics
        if row.get("channel_center_abs_error_px") is not None
    ]
    candidates.sort(
        key=lambda row: (
            -float(row["channel_center_abs_error_px"]),
            row.get("scene_id") or "",
            int(row.get("capture_index") or 0),
        )
    )
    return candidates[: max(0, int(worst_count))]


def _import_overlay_deps():
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        raise RuntimeError("Overlay generation requires cv2 and numpy.") from exc

    missing_cv2 = [
        name
        for name in ("circle", "cvtColor", "imread", "imwrite", "line", "putText", "rectangle", "resize")
        if not hasattr(cv2, name)
    ]
    missing_numpy = [
        name
        for name in ("asarray", "ascontiguousarray", "full", "rot90")
        if not hasattr(np, name)
    ]
    if missing_cv2 or missing_numpy:
        raise RuntimeError("Overlay generation requires functional cv2 and numpy installs.")
    return cv2, np


def _display_line_points(line, raw_shape):
    try:
        return raw_line_to_display(line, raw_shape)
    except Exception:
        return None


def _point_for_image(point, image_shape):
    height, width = image_shape[:2]
    x = max(0, min(width - 1, int(round(float(point[0])))))
    y = max(0, min(height - 1, int(round(float(point[1])))))
    return x, y


def _draw_solid_line(cv2, image, line, color, thickness=1):
    if not line or len(line) != 2:
        return
    cv2.line(
        image,
        _point_for_image(line[0], image.shape),
        _point_for_image(line[1], image.shape),
        color,
        int(thickness),
        lineType=cv2.LINE_AA,
    )


def _draw_dashed_line(cv2, image, line, color, thickness=1, dash_px=8, gap_px=5):
    if not line or len(line) != 2:
        return
    x0, y0 = _point_for_image(line[0], image.shape)
    x1, y1 = _point_for_image(line[1], image.shape)
    dx = float(x1 - x0)
    dy = float(y1 - y0)
    length = math.hypot(dx, dy)
    if length <= 0:
        cv2.circle(image, (x0, y0), 2, color, int(thickness), lineType=cv2.LINE_AA)
        return

    step = float(dash_px + gap_px)
    pos = 0.0
    while pos < length:
        end = min(length, pos + float(dash_px))
        start_ratio = pos / length
        end_ratio = end / length
        p0 = (int(round(x0 + dx * start_ratio)), int(round(y0 + dy * start_ratio)))
        p1 = (int(round(x0 + dx * end_ratio)), int(round(y0 + dy * end_ratio)))
        cv2.line(image, p0, p1, color, int(thickness), lineType=cv2.LINE_AA)
        pos += step


def _geometry_display_lines(geometry, raw_shape):
    if not isinstance(geometry, dict):
        return []
    lines = []
    for key in GEOMETRY_KEYS:
        line = _display_line_points(geometry.get(key), raw_shape)
        if line is not None:
            lines.append((key, line))
    return lines


def _channel_x_span_display(geometry, raw_shape, *, image_width=None):
    if not isinstance(geometry, dict):
        return None
    left_midpoint = _line_display_midpoint(geometry.get("left_wall"), raw_shape)
    right_midpoint = _line_display_midpoint(geometry.get("right_wall"), raw_shape)
    if left_midpoint is not None and right_midpoint is not None:
        x_values = [left_midpoint[0], right_midpoint[0]]
    else:
        x_values = []
        for _key, line in _geometry_display_lines(geometry, raw_shape):
            x_values.extend([line[0][0], line[1][0]])
    if not x_values:
        return None

    x0 = int(round(min(x_values)))
    x1 = int(round(max(x_values)))
    if image_width is not None:
        x0 = max(0, min(int(image_width) - 1, x0))
        x1 = max(0, min(int(image_width) - 1, x1))
    if x0 == x1:
        return None
    return [x0, x1]


def _draw_horizontal_meniscus(cv2, image, y_value, x_span, color, thickness=2):
    if y_value is None:
        return
    height, width = image.shape[:2]
    if x_span is None:
        x_span = [0, width - 1]
    y = max(0, min(height - 1, int(round(float(y_value)))))
    x0 = max(0, min(width - 1, int(round(float(x_span[0])))))
    x1 = max(0, min(width - 1, int(round(float(x_span[1])))))
    if x0 > x1:
        x0, x1 = x1, x0
    cv2.line(image, (x0, y), (x1, y), color, int(thickness), lineType=cv2.LINE_AA)


def _draw_overlay_text(cv2, image, metric, category):
    lines = [
        f"{metric.get('frame_id', '')}  scene={metric.get('scene_id', '')}",
        f"status {metric.get('label_status', '-')} -> {metric.get('predicted_status', '-')}",
        f"abs_y_err={_fmt_float(metric.get('meniscus_abs_error_px'))} px",
        f"chan_dx={_fmt_float(metric.get('channel_center_dx_px'))} w_err={_fmt_float(metric.get('channel_width_error_px'))} px",
        f"category={category or 'overlay'}",
    ]
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.42
    thickness = 1
    padding = 6
    line_gap = 4
    sizes = [cv2.getTextSize(line, font, scale, thickness)[0] for line in lines]
    panel_width = min(image.shape[1] - 1, max(width for width, _height in sizes) + padding * 2)
    text_height = max(height for _width, height in sizes)
    panel_height = min(
        image.shape[0] - 1,
        padding * 2 + len(lines) * text_height + (len(lines) - 1) * line_gap,
    )
    if panel_width > 0 and panel_height > 0:
        cv2.rectangle(image, (0, 0), (panel_width, panel_height), TEXT_BG_COLOR_BGR, -1)
    y = padding + text_height
    for line in lines:
        if y >= image.shape[0]:
            break
        cv2.putText(
            image,
            line,
            (padding, y),
            font,
            scale,
            TEXT_COLOR_BGR,
            thickness,
            lineType=cv2.LINE_AA,
        )
        y += text_height + line_gap


def draw_refuel_evaluation_overlay(raw_image, frame, label=None, seed=None, metric=None, category="overlay"):
    cv2, np = _import_overlay_deps()
    if raw_image is None:
        raise ValueError("raw_image is required.")

    raw = np.asarray(raw_image)
    if raw.ndim == 2:
        raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    elif raw.ndim == 3 and raw.shape[2] == 4:
        raw = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
    display = np.ascontiguousarray(np.rot90(raw, k=1))

    metric = dict(metric or {})
    raw_shape = frame.get("raw_image_shape") or list(raw.shape)
    label_geometry = (label or {}).get("channel_geometry") or {}
    seed_geometry = (seed or {}).get("predicted_channel_geometry") or {}

    _draw_overlay_text(cv2, display, metric, category)

    for _key, line in _geometry_display_lines(label_geometry, raw_shape):
        _draw_solid_line(cv2, display, line, LABEL_GEOMETRY_COLOR_BGR, thickness=1)
    for _key, line in _geometry_display_lines(seed_geometry, raw_shape):
        _draw_dashed_line(cv2, display, line, PREDICTED_GEOMETRY_COLOR_BGR, thickness=1)

    label_span = _channel_x_span_display(
        label_geometry,
        raw_shape,
        image_width=display.shape[1],
    )
    predicted_span = _channel_x_span_display(
        seed_geometry,
        raw_shape,
        image_width=display.shape[1],
    ) or label_span

    label_y = metric.get("label_meniscus_y_px")
    if label_y is None and (label or {}).get("status") == "visible":
        label_y = _line_display_mean_y((label or {}).get("meniscus_line"), raw_shape)
    predicted_y = metric.get("predicted_meniscus_y_px")
    if predicted_y is None and (seed or {}).get("predicted_status") == "visible":
        predicted_y = _line_display_mean_y((seed or {}).get("predicted_meniscus_line"), raw_shape)

    _draw_horizontal_meniscus(
        cv2,
        display,
        label_y,
        label_span,
        LABEL_MENISCUS_COLOR_BGR,
        thickness=2,
    )
    _draw_horizontal_meniscus(
        cv2,
        display,
        predicted_y,
        predicted_span,
        PREDICTED_MENISCUS_COLOR_BGR,
        thickness=2,
    )
    return display


def _status_mismatch_sort_key(row):
    error = row.get("meniscus_abs_error_px")
    visible_priority = 0 if row.get("label_status") == "visible" else 1
    missing_error_priority = 1 if error is None else 0
    return (
        visible_priority,
        missing_error_priority,
        -float(error or 0.0),
        row.get("scene_id") or "",
        int(row.get("capture_index") or 0),
        row.get("frame_id") or "",
    )


def select_overlay_frames(result, worst_overlay_count=25, overlay_all=False):
    frame_metrics = list(result.get("frame_metrics") or [])
    count = max(0, int(worst_overlay_count))

    status_mismatches = [
        row for row in frame_metrics if not bool(row.get("status_match"))
    ]
    status_mismatches.sort(key=_status_mismatch_sort_key)

    rows_by_scene = defaultdict(list)
    for row in frame_metrics:
        rows_by_scene[str(row.get("scene_id") or "")].append(row)

    per_scene_worst = []
    for _scene_id, rows in sorted(rows_by_scene.items()):
        per_scene_worst.extend(_worst_frames(rows, count))

    selected = {
        "worst_meniscus_errors": _worst_frames(frame_metrics, count),
        "status_mismatches": status_mismatches[:count],
        "per_scene_worst": per_scene_worst,
        "worst_channel_geometry_errors": _worst_channel_geometry_frames(frame_metrics, count),
    }
    if overlay_all:
        selected["all_evaluated_frames"] = frame_metrics
    return selected


def _read_overlay_image(cv2, path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return image


def _make_contact_sheet(image_paths, *, contact_sheet_cols=5, tile_width=420):
    cv2, np = _import_overlay_deps()
    images = []
    for path in image_paths:
        try:
            image = _read_overlay_image(cv2, path)
        except FileNotFoundError:
            continue
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            continue
        scale = float(tile_width) / float(width)
        tile_height = max(1, int(round(height * scale)))
        resized = cv2.resize(image, (int(tile_width), tile_height), interpolation=cv2.INTER_AREA)
        images.append(resized)
    if not images:
        return None

    cols = max(1, int(contact_sheet_cols))
    rows = int(math.ceil(len(images) / cols))
    tile_height = max(image.shape[0] for image in images)
    sheet = np.full((rows * tile_height, cols * int(tile_width), 3), 32, dtype=np.uint8)
    for index, image in enumerate(images):
        row = index // cols
        col = index % cols
        y0 = row * tile_height
        x0 = col * int(tile_width)
        sheet[y0 : y0 + image.shape[0], x0 : x0 + image.shape[1]] = image
    return sheet


def _metric_by_frame_id(frame_metrics):
    return {
        str(row.get("frame_id") or ""): row
        for row in frame_metrics
        if row.get("frame_id")
    }


def _append_unique(mapping, key, value):
    values = mapping[key]
    if value not in values:
        values.append(value)


def write_overlay_artifacts(
    run_dir,
    result,
    overlay_dir,
    worst_overlay_count=25,
    overlay_all=False,
    contact_sheet_cols=5,
):
    cv2, _np = _import_overlay_deps()
    run_dir = Path(run_dir).resolve()
    overlay_dir = Path(overlay_dir).resolve()
    frames_dir = overlay_dir / "frames"
    sheets_dir = overlay_dir / "contact_sheets"
    frames_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir.mkdir(parents=True, exist_ok=True)

    loaded = load_refuel_evaluation_run(run_dir, include_rejected=True)
    frames_by_id = {
        str(frame.get("frame_id") or ""): frame
        for frame in loaded["frames"]
        if frame.get("frame_id")
    }
    labels_by_frame = {
        frame_id: rows[-1]
        for frame_id, rows in loaded["label_rows_by_frame"].items()
        if rows
    }
    seeds_by_frame = loaded["analysis_by_frame"]
    prediction_source = str((result.get("summary") or {}).get("prediction_source") or "saved")

    selected = select_overlay_frames(
        result,
        worst_overlay_count=worst_overlay_count,
        overlay_all=overlay_all,
    )
    categories_by_frame = defaultdict(list)
    ordered_rows = []
    seen = set()
    for category, rows in selected.items():
        for row in rows:
            frame_id = str(row.get("frame_id") or "")
            if not frame_id:
                continue
            _append_unique(categories_by_frame, frame_id, category)
            if frame_id not in seen:
                seen.add(frame_id)
                ordered_rows.append(row)

    metrics_by_frame_id = _metric_by_frame_id(result.get("frame_metrics") or [])
    overlay_paths_by_frame = {}
    skipped = []
    frame_entries = []
    for row in ordered_rows:
        frame_id = str(row.get("frame_id") or "")
        frame = frames_by_id.get(frame_id)
        if frame is None:
            skipped.append({"frame_id": frame_id, "reason": "missing frame metadata"})
            continue
        image_relpath = str(frame.get("image_relpath") or row.get("image_relpath") or "")
        if not image_relpath:
            skipped.append({"frame_id": frame_id, "reason": "missing image_relpath"})
            continue
        image_path = run_dir / image_relpath
        try:
            raw_image = _read_overlay_image(cv2, image_path)
        except FileNotFoundError as exc:
            skipped.append({"frame_id": frame_id, "reason": str(exc)})
            continue

        categories = categories_by_frame.get(frame_id, [])
        metric = metrics_by_frame_id.get(frame_id, row)
        seed = seeds_by_frame.get(frame_id)
        if prediction_source == "rerun":
            try:
                seed = rerun_refuel_detector_prediction(
                    raw_image,
                    _analysis_params_from_seed(seed),
                )["seed"]
            except Exception:
                seed = None

        overlay = draw_refuel_evaluation_overlay(
            raw_image,
            frame,
            label=labels_by_frame.get(frame_id),
            seed=seed,
            metric=metric,
            category=",".join(categories),
        )
        overlay_path = frames_dir / f"{frame_id}_overlay.png"
        if not cv2.imwrite(str(overlay_path), overlay):
            raise IOError(f"Could not write overlay image: {overlay_path}")
        overlay_paths_by_frame[frame_id] = overlay_path
        frame_entries.append({
            "frame_id": frame_id,
            "overlay_relpath": overlay_path.relative_to(overlay_dir).as_posix(),
            "image_relpath": image_relpath,
            "categories": categories,
            "scene_id": row.get("scene_id"),
            "capture_index": row.get("capture_index"),
            "label_status": row.get("label_status"),
            "predicted_status": row.get("predicted_status"),
            "meniscus_abs_error_px": row.get("meniscus_abs_error_px"),
            "channel_center_dx_px": row.get("channel_center_dx_px"),
            "channel_center_abs_error_px": row.get("channel_center_abs_error_px"),
            "channel_width_error_px": row.get("channel_width_error_px"),
        })

    contact_sheets = {}
    for category in CONTACT_SHEET_CATEGORIES:
        paths = [
            overlay_paths_by_frame.get(str(row.get("frame_id") or ""))
            for row in selected.get(category, [])
        ]
        paths = [path for path in paths if path is not None]
        sheet = _make_contact_sheet(paths, contact_sheet_cols=contact_sheet_cols)
        if sheet is None:
            continue
        sheet_path = sheets_dir / f"{category}.png"
        if not cv2.imwrite(str(sheet_path), sheet):
            raise IOError(f"Could not write contact sheet: {sheet_path}")
        contact_sheets[category] = sheet_path.relative_to(overlay_dir).as_posix()

    manifest = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "overlay_dir": str(overlay_dir),
        "parameters": {
            "worst_overlay_count": max(0, int(worst_overlay_count)),
            "overlay_all": bool(overlay_all),
            "contact_sheet_cols": max(1, int(contact_sheet_cols)),
        },
        "categories": {
            category: [str(row.get("frame_id") or "") for row in rows]
            for category, rows in selected.items()
        },
        "contact_sheets": contact_sheets,
        "frames": frame_entries,
        "skipped": skipped,
    }
    manifest_path = overlay_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _import_refuel_detector_deps():
    try:
        from CalibrationClasses.Model import ImageAnalysisThread, RefuelCameraModel
    except Exception as exc:
        raise RuntimeError("Detector debug generation requires the FreeRTOS-interface Python app dependencies.") from exc
    return ImageAnalysisThread, RefuelCameraModel


def _coerce_debug_params(params=None):
    source = dict(DEFAULT_REFUEL_DEBUG_PARAMS)
    if isinstance(params, dict):
        for key in source:
            if params.get(key) is not None:
                source[key] = params.get(key)
    return {
        "offset": int(source["offset"]),
        "width": int(source["width"]),
        "threshold": int(source["threshold"]),
        "prominence": int(source["prominence"]),
        "empty_cutoff": float(source["empty_cutoff"]),
        "bottom_guard_px": int(source["bottom_guard_px"]),
    }


def _analysis_params_from_seed(seed):
    details = (seed or {}).get("details") or {}
    return _coerce_debug_params(details.get("analysis_parameters") or {})


def _last_row_from_seed(seed):
    details = (seed or {}).get("details") or {}
    value = details.get("last_row")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _analysis_line_to_raw(refuel_model_cls, p0, p1, raw_shape, input_shape):
    return [
        refuel_model_cls._map_analysis_point_to_raw(p0, raw_shape, input_shape),
        refuel_model_cls._map_analysis_point_to_raw(p1, raw_shape, input_shape),
    ]


def _seed_from_debug_worker(worker, raw_shape, refuel_model_cls, params):
    channel_geometry = {}
    meniscus_line = None
    input_shape = worker.input_shape
    if worker.channel_bounds is not None and input_shape is not None:
        x0, y0, w0, h0 = worker.channel_bounds
        channel_geometry = {
            "left_wall": _analysis_line_to_raw(refuel_model_cls, (x0, y0), (x0, y0 + h0), raw_shape, input_shape),
            "right_wall": _analysis_line_to_raw(refuel_model_cls, (x0 + w0, y0), (x0 + w0, y0 + h0), raw_shape, input_shape),
            "top_line": _analysis_line_to_raw(refuel_model_cls, (x0, y0), (x0 + w0, y0), raw_shape, input_shape),
            "bottom_line": _analysis_line_to_raw(refuel_model_cls, (x0, y0 + h0), (x0 + w0, y0 + h0), raw_shape, input_shape),
        }
        if worker.meniscus_row is not None and str(worker.detected_status) == "visible":
            level_y = y0 + int(worker.meniscus_row)
            meniscus_line = _analysis_line_to_raw(
                refuel_model_cls,
                (x0, level_y),
                (x0 + w0, level_y),
                raw_shape,
                input_shape,
            )

    status = str(worker.detected_status or "not_found")
    confidence = 0.0
    if status == "visible":
        confidence = 0.8
    elif status in ("full", "empty"):
        confidence = 0.35

    return {
        "detector_name": "current_refuel_detector",
        "detector_version": "phase2_offline_rerun_v5_channel_wall_profile",
        "predicted_status": status,
        "predicted_channel_geometry": channel_geometry,
        "predicted_meniscus_line": meniscus_line,
        "predicted_level_px": float(worker.level_data) if worker.level_data is not None else None,
        "confidence": float(confidence),
        "details": {
            **(worker.detected_details or {}),
            "analysis_parameters": dict(params),
        },
    }


def rerun_refuel_detector_prediction(raw_image, params=None, last_row=None, capture_debug=False):
    _cv2, np = _import_overlay_deps()
    ImageAnalysisThread, RefuelCameraModel = _import_refuel_detector_deps()
    if raw_image is None:
        raise ValueError("raw_image is required.")

    params = _coerce_debug_params(params)
    raw = np.asarray(raw_image)
    resized = RefuelCameraModel._build_analysis_working_frame(raw)
    worker = ImageAnalysisThread(
        resized,
        params["offset"],
        params["width"],
        params["threshold"],
        params["prominence"],
        params["empty_cutoff"],
        last_row,
        capture_debug=bool(capture_debug),
        bottom_guard_px=params["bottom_guard_px"],
    )
    worker.analyze_image()
    seed = _seed_from_debug_worker(worker, raw.shape, RefuelCameraModel, params)
    result = {"seed": seed}
    if capture_debug:
        debug_details = dict(worker.debug_details or {})
        debug_details.setdefault("raw_shape", list(raw.shape))
        debug_details.setdefault("rerun_predicted_status", seed["predicted_status"])
        result["debug_details"] = debug_details
        result["debug_artifacts"] = dict(worker.debug_artifacts or {})
    return result


def rerun_refuel_detector_debug(raw_image, params=None, last_row=None):
    return rerun_refuel_detector_prediction(
        raw_image,
        params=params,
        last_row=last_row,
        capture_debug=True,
    )


def _ensure_bgr(cv2, image):
    if image is None:
        return None
    if len(image.shape) == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if len(image.shape) == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image.copy()


def _fit_panel(image, *, width=640, height=360, title=""):
    cv2, np = _import_overlay_deps()
    canvas = np.full((int(height), int(width), 3), 32, dtype=np.uint8)
    if image is not None:
        image = _ensure_bgr(cv2, image)
        src_h, src_w = image.shape[:2]
        if src_h > 0 and src_w > 0:
            title_h = 24 if title else 0
            avail_h = max(1, int(height) - title_h)
            scale = min(float(width) / float(src_w), float(avail_h) / float(src_h))
            dst_w = max(1, int(round(src_w * scale)))
            dst_h = max(1, int(round(src_h * scale)))
            resized = cv2.resize(image, (dst_w, dst_h), interpolation=cv2.INTER_AREA)
            x0 = (int(width) - dst_w) // 2
            y0 = title_h + (avail_h - dst_h) // 2
            canvas[y0 : y0 + dst_h, x0 : x0 + dst_w] = resized
    if title:
        cv2.rectangle(canvas, (0, 0), (int(width) - 1, 23), TEXT_BG_COLOR_BGR, -1)
        cv2.putText(canvas, str(title), (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48, TEXT_COLOR_BGR, 1, lineType=cv2.LINE_AA)
    return canvas


def _hstack_images(images):
    _cv2, np = _import_overlay_deps()
    images = [image for image in images if image is not None]
    if not images:
        return None
    max_h = max(image.shape[0] for image in images)
    padded = []
    for image in images:
        if image.shape[0] == max_h:
            padded.append(image)
            continue
        pad = np.full((max_h, image.shape[1], 3), 32, dtype=np.uint8)
        pad[: image.shape[0], : image.shape[1]] = image
        padded.append(pad)
    return np.hstack(padded)


def _draw_rect_from_details(cv2, image, rect, color, thickness=2):
    if rect is None:
        return
    try:
        x, y, w, h = [int(round(float(v))) for v in rect]
    except Exception:
        return
    cv2.rectangle(image, (x, y), (x + w, y + h), color, int(thickness), lineType=cv2.LINE_AA)


def _draw_horizontal_line_from_details(cv2, image, y_value, color, thickness=1):
    if image is None or y_value is None:
        return
    try:
        y = int(round(float(y_value)))
    except Exception:
        return
    y = max(0, min(image.shape[0] - 1, y))
    cv2.line(image, (0, y), (image.shape[1] - 1, y), color, int(thickness), lineType=cv2.LINE_AA)


def _build_threshold_panel(debug_artifacts, debug_details):
    cv2, _np = _import_overlay_deps()
    analysis = _ensure_bgr(cv2, debug_artifacts.get("analysis_image"))
    if analysis is not None:
        for rect in debug_details.get("raw_component_bboxes") or []:
            _draw_rect_from_details(cv2, analysis, rect, (95, 95, 95), 1)
        for rect in debug_details.get("kept_contour_bboxes") or []:
            _draw_rect_from_details(cv2, analysis, rect, (0, 180, 255), 1)
        for rect in debug_details.get("merged_component_bboxes") or []:
            _draw_rect_from_details(cv2, analysis, rect, (0, 255, 0), 1)
        _draw_rect_from_details(cv2, analysis, debug_details.get("merged_head_bbox"), (0, 255, 0), 2)
        _draw_rect_from_details(cv2, analysis, debug_details.get("channel_bounds"), (255, 0, 0), 2)
        _draw_horizontal_line_from_details(cv2, analysis, debug_details.get("head_bottom_row"), (0, 255, 255), 2)
        for x_value in debug_details.get("detected_channel_wall_xs") or []:
            try:
                x = int(round(float(x_value)))
            except Exception:
                continue
            x = max(0, min(analysis.shape[1] - 1, x))
            cv2.line(analysis, (x, 0), (x, analysis.shape[0] - 1), (255, 80, 255), 1, lineType=cv2.LINE_AA)
    mask = _ensure_bgr(cv2, debug_artifacts.get("head_threshold_mask"))
    closed = _ensure_bgr(cv2, debug_artifacts.get("head_closed_mask"))
    return _hstack_images([analysis, mask, closed])


def _build_channel_panel(debug_artifacts, debug_details):
    cv2, _np = _import_overlay_deps()
    crop = _ensure_bgr(cv2, debug_artifacts.get("channel_crop_gray"))
    blur = _ensure_bgr(cv2, debug_artifacts.get("channel_crop_blur"))
    meniscus_row = debug_details.get("meniscus_row")
    fill_state = str(debug_details.get("fill_state") or "")
    for image in (crop, blur):
        if image is None or meniscus_row is None:
            continue
        y = max(0, min(image.shape[0] - 1, int(round(float(meniscus_row)))))
        color = PREDICTED_MENISCUS_COLOR_BGR if fill_state in ("", "visible") else (0, 255, 255)
        cv2.line(image, (0, y), (image.shape[1] - 1, y), color, 1, lineType=cv2.LINE_AA)
    fill_channel = _ensure_bgr(cv2, debug_artifacts.get("fill_channel_patch"))
    fill_ref = _ensure_bgr(cv2, debug_artifacts.get("fill_reference_patch"))
    return _hstack_images([crop, blur, fill_channel, fill_ref])


def _scale_series_points(values, *, x0, y0, width, height):
    if values is None:
        return []
    values = [float(value) for value in values]
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if abs(hi - lo) < 1e-9:
        lo -= 1.0
        hi += 1.0
    denom = max(1, len(values) - 1)
    points = []
    for index, value in enumerate(values):
        x = int(round(x0 + (float(index) / float(denom)) * width))
        y = int(round(y0 + height - ((value - lo) / (hi - lo)) * height))
        points.append((x, y))
    return points


def _draw_series(cv2, canvas, points, color, thickness=1):
    for p0, p1 in zip(points, points[1:]):
        cv2.line(canvas, p0, p1, color, int(thickness), lineType=cv2.LINE_AA)


def _project_label_y_to_channel_row(label_y_display, frame, debug_details):
    if label_y_display is None:
        return None
    raw_shape = frame.get("raw_image_shape")
    input_shape = debug_details.get("input_shape")
    channel_bounds = debug_details.get("channel_bounds")
    if not raw_shape or len(raw_shape) < 2 or not input_shape or len(input_shape) < 2 or not channel_bounds:
        return None
    raw_w = max(1, int(raw_shape[1]) - 1)
    analysis_h = max(1, int(input_shape[1]) - 1)
    analysis_y = float(label_y_display) * float(analysis_h) / float(raw_w)
    return float(analysis_y - float(channel_bounds[1]))


def _build_profile_panel(frame, metric, rerun_metric, debug_artifacts, debug_details):
    cv2, np = _import_overlay_deps()
    width, height = 640, 360
    canvas = np.full((height, width, 3), 28, dtype=np.uint8)
    margin_l, margin_t, margin_r, margin_b = 46, 30, 16, 40
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    x0, y0 = margin_l, margin_t
    cv2.rectangle(canvas, (x0, y0), (x0 + plot_w, y0 + plot_h), (70, 70, 70), 1)

    profile = debug_artifacts.get("profile")
    signal = debug_artifacts.get("oriented_signal")
    profile_points = _scale_series_points(profile, x0=x0, y0=y0, width=plot_w, height=plot_h)
    signal_points = _scale_series_points(signal, x0=x0, y0=y0, width=plot_w, height=plot_h)
    _draw_series(cv2, canvas, profile_points, (255, 220, 80), 1)
    _draw_series(cv2, canvas, signal_points, (0, 170, 255), 1)

    profile_len = len(profile) if profile is not None else 0

    def row_to_x(row):
        if profile_len <= 1 or row is None:
            return None
        return int(round(x0 + (float(row) / float(profile_len - 1)) * plot_w))

    search_band = debug_details.get("search_band")
    if search_band and len(search_band) == 2:
        bx0 = row_to_x(search_band[0])
        bx1 = row_to_x(search_band[1])
        if bx0 is not None and bx1 is not None:
            cv2.rectangle(canvas, (min(bx0, bx1), y0), (max(bx0, bx1), y0 + plot_h), (45, 45, 70), -1)
            _draw_series(cv2, canvas, profile_points, (255, 220, 80), 1)
            _draw_series(cv2, canvas, signal_points, (0, 170, 255), 1)

    for peak in debug_details.get("peak_rows") or []:
        px = row_to_x(peak)
        if px is not None:
            cv2.circle(canvas, (px, y0 + 8), 4, (0, 180, 255), -1, lineType=cv2.LINE_AA)

    markers = [
        ("selected", debug_details.get("selected_peak_row"), (0, 0, 255)),
        ("last", debug_details.get("last_row"), (255, 255, 0)),
        ("saved_label", _project_label_y_to_channel_row(metric.get("label_meniscus_y_px"), frame, debug_details), LABEL_MENISCUS_COLOR_BGR),
        ("rerun", rerun_metric.get("predicted_meniscus_y_px"), PREDICTED_MENISCUS_COLOR_BGR),
    ]
    if rerun_metric.get("predicted_meniscus_y_px") is not None and debug_details.get("channel_bounds"):
        markers[-1] = (
            "rerun",
            _project_label_y_to_channel_row(rerun_metric.get("predicted_meniscus_y_px"), frame, debug_details),
            PREDICTED_MENISCUS_COLOR_BGR,
        )
    for _name, row, color in markers:
        px = row_to_x(row)
        if px is not None:
            cv2.line(canvas, (px, y0), (px, y0 + plot_h), color, 1, lineType=cv2.LINE_AA)

    cv2.putText(canvas, "profile", (10, height - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 220, 80), 1, lineType=cv2.LINE_AA)
    cv2.putText(canvas, "signal/peaks", (100, height - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 170, 255), 1, lineType=cv2.LINE_AA)
    cv2.putText(canvas, "label", (225, height - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, LABEL_MENISCUS_COLOR_BGR, 1, lineType=cv2.LINE_AA)
    cv2.putText(canvas, "selected", (310, height - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, lineType=cv2.LINE_AA)
    decision = str(debug_details.get("visible_peak_reason") or "")
    final_reason = str(debug_details.get("final_decision_reason") or "")
    if decision or final_reason:
        text = f"peak={decision[:32]} final={final_reason[:36]}"
        cv2.putText(canvas, text[:100], (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, TEXT_COLOR_BGR, 1, lineType=cv2.LINE_AA)
    return canvas


def _build_detector_debug_panel(
    raw_image,
    frame,
    label,
    source_seed,
    source_metric,
    rerun_debug,
    rerun_metric,
    category,
    prediction_source="saved",
):
    cv2, np = _import_overlay_deps()
    debug_artifacts = rerun_debug.get("debug_artifacts") or {}
    debug_details = rerun_debug.get("debug_details") or {}
    rerun_seed = rerun_debug.get("seed") or {}

    saved_overlay = draw_refuel_evaluation_overlay(
        raw_image,
        frame,
        label=label,
        seed=source_seed,
        metric=source_metric,
        category=category,
    )
    threshold_panel = _build_threshold_panel(debug_artifacts, debug_details)
    channel_panel = _build_channel_panel(debug_artifacts, debug_details)
    profile_panel = _build_profile_panel(frame, source_metric, rerun_metric, debug_artifacts, debug_details)

    panels = [
        _fit_panel(saved_overlay, title=f"label vs {prediction_source} prediction"),
        _fit_panel(threshold_panel, title="analysis image / threshold mask"),
        _fit_panel(channel_panel, title="channel crop / blur / fill patches"),
        _fit_panel(profile_panel, title="profile / gradient / peak selection"),
    ]
    top = np.hstack([panels[0], panels[1]])
    bottom = np.hstack([panels[2], panels[3]])
    title_h = 54
    sheet = np.full((title_h + top.shape[0] + bottom.shape[0], top.shape[1], 3), 24, dtype=np.uint8)
    title = (
        f"{source_metric.get('frame_id', '')} scene={source_metric.get('scene_id', '')} "
        f"label={source_metric.get('label_status', '-')} "
        f"{prediction_source}={source_metric.get('predicted_status', '-')} "
        f"rerun={rerun_seed.get('predicted_status', '-')} "
        f"{prediction_source}_abs={_fmt_float(source_metric.get('meniscus_abs_error_px'))} "
        f"rerun_abs={_fmt_float(rerun_metric.get('meniscus_abs_error_px'))}"
    )
    cv2.putText(sheet, title[:180], (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, TEXT_COLOR_BGR, 1, lineType=cv2.LINE_AA)
    cv2.putText(sheet, f"category={category}", (12, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.48, TEXT_COLOR_BGR, 1, lineType=cv2.LINE_AA)
    sheet[title_h : title_h + top.shape[0], : top.shape[1]] = top
    sheet[title_h + top.shape[0] :, : bottom.shape[1]] = bottom
    return sheet


def _write_jsonl_rows(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_detector_debug_artifacts(
    run_dir,
    result,
    debug_dir,
    debug_count=25,
    debug_all=False,
    contact_sheet_cols=5,
):
    cv2, _np = _import_overlay_deps()
    run_dir = Path(run_dir).resolve()
    debug_dir = Path(debug_dir).resolve()
    frames_dir = debug_dir / "frames"
    sheets_dir = debug_dir / "contact_sheets"
    frames_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir.mkdir(parents=True, exist_ok=True)

    loaded = load_refuel_evaluation_run(run_dir, include_rejected=True)
    frames_by_id = {
        str(frame.get("frame_id") or ""): frame
        for frame in loaded["frames"]
        if frame.get("frame_id")
    }
    labels_by_frame = {
        frame_id: rows[-1]
        for frame_id, rows in loaded["label_rows_by_frame"].items()
        if rows
    }
    seeds_by_frame = loaded["analysis_by_frame"]
    scenes_by_id = loaded["scenes_by_id"]
    metrics_by_frame_id = _metric_by_frame_id(result.get("frame_metrics") or [])
    prediction_source = str((result.get("summary") or {}).get("prediction_source") or "saved")

    selected = select_overlay_frames(
        result,
        worst_overlay_count=debug_count,
        overlay_all=debug_all,
    )
    categories_by_frame = defaultdict(list)
    ordered_rows = []
    seen = set()
    for category, rows in selected.items():
        for row in rows:
            frame_id = str(row.get("frame_id") or "")
            if not frame_id:
                continue
            _append_unique(categories_by_frame, frame_id, category)
            if frame_id not in seen:
                seen.add(frame_id)
                ordered_rows.append(row)

    debug_paths_by_frame = {}
    skipped = []
    manifest_frames = []
    debug_rows = []
    for row in ordered_rows:
        frame_id = str(row.get("frame_id") or "")
        frame = frames_by_id.get(frame_id)
        if frame is None:
            skipped.append({"frame_id": frame_id, "reason": "missing frame metadata"})
            continue
        image_relpath = str(frame.get("image_relpath") or row.get("image_relpath") or "")
        if not image_relpath:
            skipped.append({"frame_id": frame_id, "reason": "missing image_relpath"})
            continue
        image_path = run_dir / image_relpath
        try:
            raw_image = _read_overlay_image(cv2, image_path)
        except FileNotFoundError as exc:
            skipped.append({"frame_id": frame_id, "reason": str(exc)})
            continue

        saved_seed = seeds_by_frame.get(frame_id)
        label = labels_by_frame.get(frame_id)
        scene = scenes_by_id.get(str(frame.get("scene_id") or ""))
        params = _analysis_params_from_seed(saved_seed)
        rerun_debug = rerun_refuel_detector_debug(
            raw_image,
            params,
        )
        rerun_metric = _frame_metric(frame, scene, label, rerun_debug.get("seed"), prediction_source="rerun")
        source_metric = metrics_by_frame_id.get(frame_id, row)
        source_seed = rerun_debug.get("seed") if prediction_source == "rerun" else saved_seed
        categories = categories_by_frame.get(frame_id, [])
        panel = _build_detector_debug_panel(
            raw_image,
            frame,
            label,
            source_seed,
            source_metric,
            rerun_debug,
            rerun_metric,
            ",".join(categories),
            prediction_source=prediction_source,
        )
        frame_path = frames_dir / f"{frame_id}_steps.png"
        if not cv2.imwrite(str(frame_path), panel):
            raise IOError(f"Could not write debug panel: {frame_path}")
        debug_paths_by_frame[frame_id] = frame_path

        debug_summary = {
            "frame_id": frame_id,
            "scene_id": row.get("scene_id"),
            "capture_index": row.get("capture_index"),
            "image_relpath": image_relpath,
            "categories": categories,
            "prediction_source": prediction_source,
            "source_predicted_status": source_metric.get("predicted_status"),
            "rerun_predicted_status": rerun_metric.get("predicted_status"),
            "label_status": source_metric.get("label_status"),
            "source_meniscus_abs_error_px": source_metric.get("meniscus_abs_error_px"),
            "rerun_meniscus_abs_error_px": rerun_metric.get("meniscus_abs_error_px"),
            "source_channel_center_dx_px": source_metric.get("channel_center_dx_px"),
            "source_channel_center_abs_error_px": source_metric.get("channel_center_abs_error_px"),
            "source_channel_width_error_px": source_metric.get("channel_width_error_px"),
            "rerun_channel_center_dx_px": rerun_metric.get("channel_center_dx_px"),
            "rerun_channel_center_abs_error_px": rerun_metric.get("channel_center_abs_error_px"),
            "rerun_channel_width_error_px": rerun_metric.get("channel_width_error_px"),
            "analysis_parameters": params,
            "debug_details": rerun_debug.get("debug_details") or {},
        }
        debug_rows.append(debug_summary)
        manifest_frames.append({
            **{key: value for key, value in debug_summary.items() if key != "debug_details"},
            "steps_relpath": frame_path.relative_to(debug_dir).as_posix(),
        })

    contact_sheets = {}
    for category in CONTACT_SHEET_CATEGORIES:
        paths = [
            debug_paths_by_frame.get(str(row.get("frame_id") or ""))
            for row in selected.get(category, [])
        ]
        paths = [path for path in paths if path is not None]
        sheet = _make_contact_sheet(paths, contact_sheet_cols=contact_sheet_cols)
        if sheet is None:
            continue
        sheet_path = sheets_dir / f"{category}_steps.png"
        if not cv2.imwrite(str(sheet_path), sheet):
            raise IOError(f"Could not write debug contact sheet: {sheet_path}")
        contact_sheets[category] = sheet_path.relative_to(debug_dir).as_posix()

    frame_debug_path = debug_dir / "frame_debug.jsonl"
    _write_jsonl_rows(frame_debug_path, debug_rows)
    manifest = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "debug_dir": str(debug_dir),
        "parameters": {
            "debug_count": max(0, int(debug_count)),
            "debug_all": bool(debug_all),
            "contact_sheet_cols": max(1, int(contact_sheet_cols)),
        },
        "categories": {
            category: [str(row.get("frame_id") or "") for row in rows]
            for category, rows in selected.items()
        },
        "contact_sheets": contact_sheets,
        "frame_debug_relpath": frame_debug_path.relative_to(debug_dir).as_posix(),
        "frames": manifest_frames,
        "skipped": skipped,
    }
    manifest_path = debug_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _fmt_float(value, digits=3):
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def format_evaluation_report(result, worst_count=10):
    if result.get("prediction_source") == "both":
        sections = []
        for source_name in ("saved", "rerun"):
            source_result = (result.get("sources") or {}).get(source_name)
            if source_result is None:
                continue
            sections.append(
                f"Prediction Source: {source_name}\n"
                f"{format_evaluation_report(source_result, worst_count=worst_count)}"
            )
        return "\n\n".join(sections)

    summary = result["summary"]
    lines = [
        "Refuel Detector Evaluation",
        f"Run: {summary['run_dir']}",
        f"Prediction source: {summary.get('prediction_source', 'saved')}",
        "",
        "Coverage",
        f"  Frames: {summary['frame_count']}",
        f"  Evaluated frames: {summary['evaluated_frame_count']}",
        f"  Scenes: {summary['scene_count']}",
        f"  Labels: {summary['label_count']}",
        f"  Analysis seeds: {summary['analysis_seed_count']}",
        f"  Missing labels: {summary['missing_label_count']}",
        f"  Duplicate label frames: {summary['duplicate_label_frame_count']}",
        f"  Validation errors: {summary['validation_error_count']}",
    ]
    if result.get("warnings"):
        lines.append("")
        lines.append("Warnings")
        for warning in result["warnings"]:
            lines.append(f"  - {warning}")

    lines.extend([
        "",
        "Status",
        f"  Accuracy: {_fmt_float(summary['status_accuracy'])}",
        f"  Label counts: {json.dumps(summary['label_status_counts'], sort_keys=True)}",
        f"  Prediction counts: {json.dumps(summary['predicted_status_counts'], sort_keys=True)}",
        "  Confusion matrix:",
    ])
    for label_status, pred_counts in result["confusion_matrix"].items():
        lines.append(f"    {label_status}: {json.dumps(pred_counts, sort_keys=True)}")

    meniscus = summary["meniscus_y_error_px"]
    level = summary["level_error_px"]
    channel = summary.get("channel_x_error_px") or {}
    channel_center = channel.get("channel_center_dx_px") or _signed_error_summary([])
    channel_width = channel.get("channel_width_error_px") or _signed_error_summary([])
    lines.extend([
        "",
        "Visible Meniscus Error (display px)",
        f"  Count: {meniscus['count']}",
        f"  MAE: {_fmt_float(meniscus['mae'])}",
        f"  Median abs: {_fmt_float(meniscus['median_abs_error'])}",
        f"  RMSE: {_fmt_float(meniscus['rmse'])}",
        f"  P90 abs: {_fmt_float(meniscus['p90_abs_error'])}",
        f"  Max abs: {_fmt_float(meniscus['max_abs_error'])}",
        "",
        "Visible Level Error (display px)",
        f"  Count: {level['count']}",
        f"  MAE: {_fmt_float(level['mae'])}",
        f"  Median abs: {_fmt_float(level['median_abs_error'])}",
        f"  RMSE: {_fmt_float(level['rmse'])}",
        f"  P90 abs: {_fmt_float(level['p90_abs_error'])}",
        f"  Max abs: {_fmt_float(level['max_abs_error'])}",
        "",
        "Channel Geometry Error (display x px)",
        f"  Count: {channel_center['count']}",
        f"  Center mean signed: {_fmt_float(channel_center.get('mean_error'))}",
        f"  Center MAE: {_fmt_float(channel_center.get('mae'))}",
        f"  Center max abs: {_fmt_float(channel_center.get('max_abs_error'))}",
        f"  Width mean signed: {_fmt_float(channel_width.get('mean_error'))}",
        f"  Width MAE: {_fmt_float(channel_width.get('mae'))}",
        "",
        "Scenes",
    ])
    for scene_id, scene in result["scenes"].items():
        men = scene["meniscus_y_error_px"]
        scene_channel = scene.get("channel_x_error_px") or {}
        scene_center = scene_channel.get("channel_center_dx_px") or _signed_error_summary([])
        lines.append(
            f"  {scene_id} tags={scene['scene_tags']} frames={scene['frame_count']} "
            f"status_acc={_fmt_float(scene['status_accuracy'])} "
            f"meniscus_mae={_fmt_float(men['mae'])} meniscus_count={men['count']} "
            f"channel_center_mean={_fmt_float(scene_center.get('mean_error'))} "
            f"channel_center_mae={_fmt_float(scene_center.get('mae'))}"
        )

    worst = _worst_frames(result["frame_metrics"], worst_count)
    lines.append("")
    lines.append(f"Worst Visible Meniscus Failures (top {len(worst)})")
    for row in worst:
        lines.append(
            f"  {row['frame_id']} scene={row['scene_id']} "
            f"label_y={_fmt_float(row['label_meniscus_y_px'])} "
            f"pred_y={_fmt_float(row['predicted_meniscus_y_px'])} "
            f"abs_err={_fmt_float(row['meniscus_abs_error_px'])} "
            f"status={row['label_status']}->{row['predicted_status']}"
        )
    worst_channel = _worst_channel_geometry_frames(result["frame_metrics"], worst_count)
    lines.append("")
    lines.append(f"Worst Channel Geometry Errors (top {len(worst_channel)})")
    for row in worst_channel:
        lines.append(
            f"  {row['frame_id']} scene={row['scene_id']} "
            f"center_dx={_fmt_float(row.get('channel_center_dx_px'))} "
            f"center_abs={_fmt_float(row.get('channel_center_abs_error_px'))} "
            f"width_err={_fmt_float(row.get('channel_width_error_px'))} "
            f"status={row['label_status']}->{row['predicted_status']}"
        )
    return "\n".join(lines)


def write_json_report(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


def frame_metrics_for_result(result):
    if result.get("prediction_source") == "both":
        rows = []
        for source_name in ("saved", "rerun"):
            source_result = (result.get("sources") or {}).get(source_name) or {}
            rows.extend(source_result.get("frame_metrics") or [])
        return rows
    return list(result.get("frame_metrics") or [])


def write_csv_frame_metrics(path, frame_metrics):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in frame_metrics:
            writer.writerow({key: _csv_value(row.get(key)) for key in CSV_FIELDNAMES})


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate refuel detector seeds against manual labels.")
    parser.add_argument("run_dir", help="Path to a RefuelLevelDatasetCaptureProcess run directory.")
    parser.add_argument("--include-rejected", action="store_true", help="Include frames marked rejected.")
    parser.add_argument(
        "--prediction-source",
        choices=("saved", "rerun", "both"),
        default="saved",
        help="Score saved analysis seeds, current detector reruns, or both.",
    )
    parser.add_argument("--json-out", help="Optional path for a JSON report.")
    parser.add_argument("--csv-out", help="Optional path for per-frame CSV metrics.")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero on dataset validation issues.")
    parser.add_argument("--worst", type=int, default=10, help="Number of worst visible failures to print.")
    parser.add_argument("--overlay-dir", help="Optional directory for annotated visual debug overlays.")
    parser.add_argument(
        "--worst-overlay-count",
        type=int,
        default=25,
        help="Number of worst/error frames per overlay category.",
    )
    parser.add_argument(
        "--overlay-all",
        action="store_true",
        help="Write overlays for all evaluated frames in addition to representative failures.",
    )
    parser.add_argument(
        "--contact-sheet-cols",
        type=int,
        default=5,
        help="Number of columns in generated overlay/debug contact sheets.",
    )
    parser.add_argument("--debug-dir", help="Optional directory for detector step diagnostic panels.")
    parser.add_argument(
        "--debug-count",
        type=int,
        default=25,
        help="Number of worst/error frames per debug category.",
    )
    parser.add_argument(
        "--debug-all",
        action="store_true",
        help="Write detector step diagnostics for all evaluated frames.",
    )
    return parser.parse_args(argv)


def _has_strict_failures(result):
    if result.get("prediction_source") == "both":
        return any(
            _has_strict_failures(source_result)
            for source_result in (result.get("sources") or {}).values()
        )
    failures = result.get("strict_failures") or {}
    return any(bool(value) for value in failures.values())


def _source_results_for_artifacts(result):
    if result.get("prediction_source") == "both":
        return [
            (source_name, source_result)
            for source_name, source_result in ((result.get("sources") or {}).items())
            if source_name in ("saved", "rerun") and source_result is not None
        ]
    return [(None, result)]


def main(argv=None):
    args = parse_args(argv)
    result = evaluate_refuel_run(
        args.run_dir,
        include_rejected=args.include_rejected,
        prediction_source=args.prediction_source,
    )
    print(format_evaluation_report(result, worst_count=args.worst))
    if args.json_out:
        write_json_report(args.json_out, result)
    if args.csv_out:
        write_csv_frame_metrics(args.csv_out, frame_metrics_for_result(result))
    if args.overlay_dir:
        for source_name, source_result in _source_results_for_artifacts(result):
            overlay_dir = Path(args.overlay_dir)
            if source_name is not None:
                overlay_dir = overlay_dir / source_name
            manifest = write_overlay_artifacts(
                args.run_dir,
                source_result,
                overlay_dir,
                worst_overlay_count=args.worst_overlay_count,
                overlay_all=args.overlay_all,
                contact_sheet_cols=args.contact_sheet_cols,
            )
            print("")
            label = f"Overlay artifacts ({source_name})" if source_name else "Overlay artifacts"
            print(f"{label}: {manifest['overlay_dir']}")
            print(f"  Frame overlays: {len(manifest['frames'])}")
            print(f"  Contact sheets: {len(manifest['contact_sheets'])}")
            if manifest.get("skipped"):
                print(f"  Skipped overlays: {len(manifest['skipped'])}")
    if args.debug_dir:
        for source_name, source_result in _source_results_for_artifacts(result):
            debug_dir = Path(args.debug_dir)
            if source_name is not None:
                debug_dir = debug_dir / source_name
            manifest = write_detector_debug_artifacts(
                args.run_dir,
                source_result,
                debug_dir,
                debug_count=args.debug_count,
                debug_all=args.debug_all,
                contact_sheet_cols=args.contact_sheet_cols,
            )
            print("")
            label = f"Detector debug artifacts ({source_name})" if source_name else "Detector debug artifacts"
            print(f"{label}: {manifest['debug_dir']}")
            print(f"  Step panels: {len(manifest['frames'])}")
            print(f"  Contact sheets: {len(manifest['contact_sheets'])}")
            if manifest.get("skipped"):
                print(f"  Skipped debug panels: {len(manifest['skipped'])}")
    if args.strict and _has_strict_failures(result):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
