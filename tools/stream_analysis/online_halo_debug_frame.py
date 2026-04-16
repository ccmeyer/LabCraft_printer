from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import cv2
import numpy as np

from tools.stream_analysis import dataset as dataset_mod
from tools.stream_analysis import online_report as report_mod
from tools.stream_analysis import online_runtime as runtime_mod
from tools.stream_analysis import silhouette as silhouette_mod
from tools.stream_analysis import volume as volume_mod


ANALYSIS_NAME = "online_halo_debug_frame"
STAGE_DIRNAME = "online_halo_debug_frames"
DEFAULT_CONFIG = {
    "lambda_rb": 0.75,
    "boundary_band_radius_px": 1,
    "suspicious_boundary_chroma_min": 20.0,
    "suspicious_signed_halo_min": 14.0,
    "suspicious_inward_offset_min_px": 1.0,
    "suspicious_min_vertical_normal": 0.45,
    "candidate_min_window_px": 12.0,
    "detached_cap_window_frac": 0.18,
    "attached_lower_window_frac": 0.16,
    "suspicion_smooth_window": 5,
    "min_arc_point_count": 8,
    "sample_spacing_px": 4.0,
    "profile_radius_px": 6,
    "max_inward_shift_px": 4,
    "profile_smooth_window": 3,
    "profile_min_transition": 2.0,
    "profile_min_inside_signed_halo": 16.0,
    "profile_min_outside_signed_halo": 16.0,
    "profile_min_signed_halo_margin": 6.0,
    "max_profiles": 12,
    "min_profile_spacing_px": 10.0,
}


def _load_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _json_builtin(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_builtin(item) for item in value]
    return value


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_builtin(payload), indent=2), encoding="utf-8")
    return path


def _write_csv(path: Path, rows: list[dict], *, fieldnames: list[str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    row_list = [dict(row) for row in list(rows or [])]
    if fieldnames is None:
        fieldnames = []
        seen = set()
        for row in row_list:
            for key in row.keys():
                if key in seen:
                    continue
                seen.add(key)
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in row_list:
            writer.writerow({name: _json_builtin(row.get(name)) for name in fieldnames})
    return path


def _resolved_config(config: dict | None = None) -> dict:
    merged = dict(DEFAULT_CONFIG)
    for key, default in DEFAULT_CONFIG.items():
        if not isinstance(config, dict) or key not in config:
            continue
        value = config.get(key)
        try:
            if isinstance(default, int):
                merged[key] = int(value)
            else:
                merged[key] = float(value)
        except Exception:
            merged[key] = default
    return merged


def _output_root(experiment_root: Path, run_id: str, capture_id: str, output_root=None) -> Path:
    if output_root not in (None, ""):
        return Path(str(output_root)).expanduser().resolve()
    return (
        Path(experiment_root).resolve()
        / "analysis"
        / STAGE_DIRNAME
        / str(run_id)
        / str(capture_id)
    )


def _frame_capture_id(frame_row: dict) -> str | None:
    image_ref = dict(frame_row.get("image_ref") or {})
    return report_mod._clean_text(frame_row.get("capture_id")) or report_mod._clean_text(
        image_ref.get("capture_id")
    )


def _frame_delay_us(frame_row: dict) -> int | None:
    image_ref = dict(frame_row.get("image_ref") or {})
    delay_us = report_mod._int_or_none(frame_row.get("delay_us"))
    if delay_us is None:
        delay_us = report_mod._int_or_none(frame_row.get("flash_delay_us"))
    if delay_us is None:
        delay_us = report_mod._int_or_none(image_ref.get("delay_us"))
    return delay_us


def _read_bgr_image(path: Path):
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"Unable to read image: {path}")
    return image


def _load_frame_context(experiment_root: str | Path, run_id: str, capture_id: str) -> dict:
    experiment_root = dataset_mod.resolve_experiment_root(experiment_root)
    run_dir = (
        experiment_root
        / "calibration_recordings"
        / dataset_mod.ONLINE_STREAM_PROCESS_NAME
        / str(run_id)
    )
    if not run_dir.exists():
        raise FileNotFoundError(f"Online stream run not found: {run_dir}")

    plan_snapshot = report_mod._load_json(run_dir / "plan_snapshot.json")
    correction_context = report_mod._resolve_online_stream_correction_context(
        experiment_root,
        run_dir,
        plan_snapshot=plan_snapshot,
        correction_cache={},
    )
    frame_rows = report_mod._iter_jsonl(run_dir / "frames.jsonl")
    frame_row = next(
        (dict(row) for row in list(frame_rows or []) if _frame_capture_id(dict(row or {})) == str(capture_id)),
        None,
    )
    if frame_row is None:
        raise ValueError(f"capture_id={capture_id!r} was not found in {run_dir / 'frames.jsonl'}")

    image_ref = dict(frame_row.get("image_ref") or {})
    image_relpath = report_mod._clean_text(image_ref.get("image_relpath")) or report_mod._clean_text(
        frame_row.get("image_relpath")
    )
    if image_relpath is None:
        raise ValueError(f"Frame {capture_id!r} is missing image_relpath.")
    image_path = (run_dir / image_relpath).resolve()
    background_relpath = report_mod._clean_text(image_ref.get("subtract_background_image_relpath"))
    background_path = None if background_relpath is None else (run_dir / background_relpath).resolve()

    delay_us = _frame_delay_us(frame_row)
    if delay_us is None:
        raise ValueError(f"Frame {capture_id!r} is missing delay_us/flash_delay_us.")

    frame_image = _read_bgr_image(image_path)
    background_image = None
    if background_path is not None and background_path.exists():
        background_image = _read_bgr_image(background_path)

    return {
        "experiment_root": Path(experiment_root).resolve(),
        "run_id": str(run_id),
        "capture_id": str(capture_id),
        "run_dir": run_dir.resolve(),
        "plan_snapshot": dict(plan_snapshot or {}),
        "analysis_config": (plan_snapshot.get("analysis_config") or None),
        "correction_context": dict(correction_context),
        "frame_row": dict(frame_row),
        "image_path": image_path,
        "background_path": background_path,
        "frame_image": frame_image,
        "background_image": background_image,
        "delay_us": int(delay_us),
        "emergence_time_us": int(correction_context["emergence_time_us"]),
        "nozzle_center_px": list(correction_context["nozzle_center_px"]),
        "capture_ref": dict(image_ref),
        "capture_index": report_mod._int_or_none(frame_row.get("capture_index"))
        or report_mod._int_or_none(image_ref.get("capture_index")),
    }


def _analyze_stage3_stage4(
    *,
    frame_image,
    background_image,
    nozzle_center_px,
    delay_us: int,
    emergence_time_us: int,
    analysis_config: dict | None,
    capture_ref: dict | None,
    capture_index: int | None,
    gray_override=None,
) -> dict:
    config = runtime_mod._resolved_analysis_config(analysis_config)
    gray_frame = (
        runtime_mod._coerce_analysis_gray_frame(frame_image, color_order="bgr")
        if gray_override is None
        else np.asarray(gray_override, dtype=np.uint8)
    )
    stage3_frame = silhouette_mod._analyze_stage3_gray(
        ANALYSIS_NAME,
        runtime_mod._frame_row(
            delay_us=int(delay_us),
            emergence_time_us=int(emergence_time_us),
            capture_ref=capture_ref,
            capture_index=capture_index,
        ),
        runtime_mod._tracked_row(nozzle_center_px),
        gray_frame,
        roi_width_frac=runtime_mod._ROI_WIDTH_FRAC,
        roi_top_frac=runtime_mod._ROI_TOP_FRAC,
        roi_bottom_frac=runtime_mod._ROI_BOTTOM_FRAC,
        corridor_width_frac=runtime_mod._CORRIDOR_WIDTH_FRAC,
        nozzle_guard_px=int(config["nozzle_guard_px"]),
        min_component_area_px=int(config["min_component_area_px"]),
    )
    stage4_frame = volume_mod._analyze_stage4_frame(
        stage3_frame,
        near_bottom_px=int(config["detached_near_bottom_warning_px"]),
    )
    runtime_result = None
    if gray_override is None:
        runtime_result = runtime_mod.analyze_online_stream_frame(
            frame_image=frame_image,
            background_image=background_image,
            nozzle_center_px=list(nozzle_center_px),
            delay_us=int(delay_us),
            emergence_time_us=int(emergence_time_us),
            analysis_config=analysis_config,
            capture_ref=capture_ref,
            capture_index=capture_index,
            frame_color_order="bgr",
            background_color_order="bgr",
        )
    return {
        "stage3_frame": stage3_frame,
        "stage4_frame": stage4_frame,
        "gray_frame": gray_frame,
        "runtime_result": runtime_result,
    }


def _edge_rows_volume_nl(edge_rows: list[dict]) -> float:
    return float(sum(volume_mod._row_volume_um3(row) for row in list(edge_rows or []))) / float(
        volume_mod.UM3_PER_NL
    )


def _component_kind(component: dict) -> str:
    role = str(component.get("component_role") or "")
    return "attached" if role == "attached_primary" else "detached"


def _component_key(component: dict) -> tuple[str, str, int]:
    return (
        str(_component_kind(component)),
        str(component.get("component_id") or ""),
        int(component.get("component_rank") or 0),
    )


def _component_volume_map(component_volume_rows: list[dict]) -> dict[str, float]:
    volumes = {}
    for row in list(component_volume_rows or []):
        component_id = str(row.get("component_id") or "")
        if component_id:
            volumes[component_id] = float(row.get("component_volume_nl") or 0.0)
    return volumes


def _mask_to_contour(mask: np.ndarray):
    if mask is None or not np.any(mask > 0):
        return None
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    points = np.asarray(contour, dtype=np.float32).reshape((-1, 2))
    if points.shape[0] < 3:
        return None
    return points


def _component_entries(stage3_frame: dict, stage4_frame: dict, *, image_shape) -> list[dict]:
    roi = dict(stage3_frame.get("roi") or {})
    component_volumes = _component_volume_map(stage4_frame.get("component_volume_rows") or [])
    entries = []
    for component in list(stage3_frame.get("accepted_components") or []):
        component_state = dict(component or {})
        full_mask = runtime_mod._project_component_mask(component_state, roi, image_shape)
        contour = _mask_to_contour(full_mask)
        moments = None if full_mask is None else cv2.moments(full_mask)
        centroid = None
        if moments is not None and float(moments.get("m00") or 0.0) > 0.0:
            centroid = np.asarray(
                [
                    float(moments["m10"] / moments["m00"]),
                    float(moments["m01"] / moments["m00"]),
                ],
                dtype=np.float32,
            )
        entries.append(
            {
                "component": component_state,
                "component_kind": _component_kind(component_state),
                "component_key": _component_key(component_state),
                "component_id": str(component_state.get("component_id") or ""),
                "component_rank": int(component_state.get("component_rank") or 0),
                "full_mask": full_mask,
                "contour": contour,
                "centroid": centroid,
                "edge_rows": list(component_state.get("edge_rows") or []),
                "volume_nl": float(
                    component_volumes.get(
                        str(component_state.get("component_id") or ""),
                        _edge_rows_volume_nl(component_state.get("edge_rows") or []),
                    )
                ),
            }
        )
    return entries


def _safe_unit(vector) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if not np.isfinite(norm) or norm <= 1.0e-6:
        return np.asarray([1.0, 0.0], dtype=np.float32)
    return arr / norm


def _sample_mask(mask: np.ndarray | None, point) -> int:
    if mask is None or mask.size <= 0:
        return 0
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    x = max(0, min(mask.shape[1] - 1, x))
    y = max(0, min(mask.shape[0] - 1, y))
    return int(mask[y, x] > 0)


def _sample_scalar(image: np.ndarray, point) -> float:
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    x = max(0, min(image.shape[1] - 1, x))
    y = max(0, min(image.shape[0] - 1, y))
    return float(image[y, x])


def _sample_bgr(image: np.ndarray, point) -> tuple[int, int, int]:
    x = int(round(float(point[0])))
    y = int(round(float(point[1])))
    x = max(0, min(image.shape[1] - 1, x))
    y = max(0, min(image.shape[0] - 1, y))
    pixel = image[y, x]
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _cumulative_arc_lengths(contour: np.ndarray) -> np.ndarray:
    if contour is None or len(contour) <= 0:
        return np.zeros(0, dtype=np.float32)
    lengths = np.zeros(len(contour), dtype=np.float32)
    for index in range(1, len(contour)):
        lengths[index] = lengths[index - 1] + float(
            np.linalg.norm(np.asarray(contour[index]) - np.asarray(contour[index - 1]))
        )
    return lengths


def _circular_smooth(values, window: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32)
    if arr.size <= 0 or int(window) <= 1:
        return arr.copy()
    radius = int(max(1, window // 2))
    padded = np.pad(arr, (radius, radius), mode="wrap")
    kernel = np.ones((radius * 2) + 1, dtype=np.float32) / float((radius * 2) + 1)
    return np.convolve(padded, kernel, mode="valid").astype(np.float32)


def _median_smooth(values, window: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32)
    if arr.size <= 0 or int(window) <= 1:
        return arr.copy()
    radius = int(max(1, window // 2))
    smoothed = np.zeros_like(arr)
    for index in range(arr.size):
        lo = max(0, index - radius)
        hi = min(arr.size, index + radius + 1)
        smoothed[index] = float(np.median(arr[lo:hi]))
    return smoothed


def _contiguous_true_runs(flags: list[bool] | np.ndarray) -> list[list[int]]:
    values = [bool(item) for item in ([] if flags is None else list(flags))]
    if not values or not any(values):
        return []
    if all(values):
        return [list(range(len(values)))]

    starts = []
    for index, value in enumerate(values):
        prev_value = values[index - 1] if index > 0 else values[-1]
        if value and not prev_value:
            starts.append(index)

    runs = []
    for start in starts:
        current = []
        index = start
        while True:
            if not values[index]:
                break
            current.append(index)
            index = (index + 1) % len(values)
            if index == start:
                break
        if current:
            runs.append(current)
    return runs


def _arc_length_from_indexes(contour: np.ndarray, indexes: list[int]) -> float:
    if contour is None or len(indexes) <= 1:
        return 0.0
    total = 0.0
    for prev_index, next_index in zip(indexes[:-1], indexes[1:]):
        total += float(np.linalg.norm(np.asarray(contour[next_index]) - np.asarray(contour[prev_index])))
    return float(total)


def _contour_normals(contour: np.ndarray, centroid, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if contour is None or len(contour) <= 0:
        return np.zeros((0, 2), dtype=np.float32), np.zeros((0, 2), dtype=np.float32)
    center = np.asarray(centroid if centroid is not None else np.mean(contour, axis=0), dtype=np.float32)
    tangents = np.zeros((len(contour), 2), dtype=np.float32)
    normals = np.zeros((len(contour), 2), dtype=np.float32)
    for index in range(len(contour)):
        prev_point = np.asarray(contour[(index - 2) % len(contour)], dtype=np.float32)
        next_point = np.asarray(contour[(index + 2) % len(contour)], dtype=np.float32)
        tangent = _safe_unit(next_point - prev_point)
        normal = _safe_unit(np.asarray([-tangent[1], tangent[0]], dtype=np.float32))
        point = np.asarray(contour[index], dtype=np.float32)
        radial = _safe_unit(point - center)
        if float(np.dot(normal, radial)) < 0.0:
            normal = -normal
        plus_inside = _sample_mask(mask, point + (normal * 1.5))
        minus_inside = _sample_mask(mask, point - (normal * 1.5))
        if plus_inside and not minus_inside:
            normal = -normal
        tangents[index] = tangent
        normals[index] = _safe_unit(normal)
    return tangents, normals


def _boundary_chroma_scores(bgr_frame: np.ndarray, contour: np.ndarray, normals: np.ndarray, *, band_radius_px: int) -> np.ndarray:
    scores = np.zeros(len(contour), dtype=np.float32)
    offsets = list(range(-int(max(0, band_radius_px)), int(max(0, band_radius_px)) + 1))
    for index, point in enumerate(contour):
        normal = normals[index]
        values = []
        for offset in offsets:
            sample_point = np.asarray(point, dtype=np.float32) + (normal * float(offset))
            b_value, _g_value, r_value = _sample_bgr(bgr_frame, sample_point)
            values.append(abs(float(r_value) - float(b_value)))
        scores[index] = float(np.mean(values)) if values else 0.0
    return scores


def _signed_halo_value(normal, *, b_value: int, r_value: int) -> float:
    normal_arr = np.asarray(normal, dtype=np.float32)
    return float(normal_arr[1]) * float(float(b_value) - float(r_value))


def _boundary_signed_halo_scores(
    bgr_frame: np.ndarray,
    contour: np.ndarray,
    normals: np.ndarray,
    *,
    band_radius_px: int,
) -> np.ndarray:
    scores = np.zeros(len(contour), dtype=np.float32)
    outside_offsets = [0] + list(range(1, int(max(0, band_radius_px)) + 1))
    inside_offsets = list(range(-int(max(1, band_radius_px)), 0))
    for index, point in enumerate(contour):
        normal = normals[index]
        outside_values = []
        inside_values = []
        for offset in outside_offsets:
            sample_point = np.asarray(point, dtype=np.float32) + (normal * float(offset))
            b_value, _g_value, r_value = _sample_bgr(bgr_frame, sample_point)
            outside_values.append(max(0.0, _signed_halo_value(normal, b_value=b_value, r_value=r_value)))
        for offset in inside_offsets:
            sample_point = np.asarray(point, dtype=np.float32) + (normal * float(offset))
            b_value, _g_value, r_value = _sample_bgr(bgr_frame, sample_point)
            inside_values.append(max(0.0, _signed_halo_value(normal, b_value=b_value, r_value=r_value)))
        outside_mean = float(np.mean(outside_values)) if outside_values else 0.0
        inside_mean = float(np.mean(inside_values)) if inside_values else 0.0
        scores[index] = float(max(0.0, outside_mean - inside_mean))
    return scores


def _inward_offsets_to_mask(contour: np.ndarray, normals: np.ndarray, robust_mask: np.ndarray | None, *, max_shift_px: int) -> np.ndarray:
    offsets = np.zeros(len(contour), dtype=np.float32)
    if robust_mask is None or robust_mask.size <= 0:
        return offsets
    for index, point in enumerate(contour):
        if _sample_mask(robust_mask, point):
            offsets[index] = 0.0
            continue
        normal = normals[index]
        offset_value = 0.0
        for step in range(1, int(max_shift_px) + 1):
            sample_point = np.asarray(point, dtype=np.float32) - (normal * float(step))
            if _sample_mask(robust_mask, sample_point):
                offset_value = float(step)
                break
        offsets[index] = float(offset_value)
    return offsets


def _component_candidate_region_flags(
    *,
    component_kind: str,
    contour: np.ndarray,
    normals: np.ndarray,
    config: dict,
) -> list[tuple[str, np.ndarray]]:
    if contour is None or len(contour) <= 0:
        return []
    y_values = np.asarray(contour[:, 1], dtype=np.float32)
    y_min = float(np.min(y_values))
    y_max = float(np.max(y_values))
    height = max(1.0, y_max - y_min)
    min_window_px = float(config["candidate_min_window_px"])
    vertical_min = float(config["suspicious_min_vertical_normal"])
    regions = []

    if str(component_kind) == "detached":
        cap_window_px = max(min_window_px, height * float(config["detached_cap_window_frac"]))
        top_flags = np.logical_and(
            y_values <= float(y_min + cap_window_px),
            normals[:, 1] <= -vertical_min,
        )
        bottom_flags = np.logical_and(
            y_values >= float(y_max - cap_window_px),
            normals[:, 1] >= vertical_min,
        )
        regions.append(("detached_top_cap", np.asarray(top_flags, dtype=bool)))
        regions.append(("detached_bottom_cap", np.asarray(bottom_flags, dtype=bool)))
        return regions

    lower_window_px = max(min_window_px, height * float(config["attached_lower_window_frac"]))
    lower_flags = np.logical_and(
        y_values >= float(y_max - lower_window_px),
        normals[:, 1] >= vertical_min,
    )
    regions.append(("attached_lower_boundary", np.asarray(lower_flags, dtype=bool)))
    return regions


def _detect_suspicious_arcs(
    *,
    component_kind: str,
    contour: np.ndarray,
    mask: np.ndarray,
    robust_mask: np.ndarray | None,
    centroid,
    bgr_frame: np.ndarray,
    config: dict,
) -> dict:
    if contour is None or len(contour) <= 0:
        return {
            "contour": contour,
            "tangents": np.zeros((0, 2), dtype=np.float32),
            "normals": np.zeros((0, 2), dtype=np.float32),
            "boundary_chroma": np.zeros(0, dtype=np.float32),
            "signed_halo": np.zeros(0, dtype=np.float32),
            "inward_offsets": np.zeros(0, dtype=np.float32),
            "smoothed_boundary_chroma": np.zeros(0, dtype=np.float32),
            "smoothed_signed_halo": np.zeros(0, dtype=np.float32),
            "smoothed_inward_offsets": np.zeros(0, dtype=np.float32),
            "vertical_normal_weight": np.zeros(0, dtype=np.float32),
            "suspicion_score": np.zeros(0, dtype=np.float32),
            "suspicious_flags": np.zeros(0, dtype=bool),
            "candidate_flags": np.zeros(0, dtype=bool),
            "suspicious_arcs": [],
            "candidate_arcs": [],
            "arc_lengths": np.zeros(0, dtype=np.float32),
        }

    tangents, normals = _contour_normals(contour, centroid, mask)
    boundary_chroma = _boundary_chroma_scores(
        bgr_frame,
        contour,
        normals,
        band_radius_px=int(config["boundary_band_radius_px"]),
    )
    signed_halo = _boundary_signed_halo_scores(
        bgr_frame,
        contour,
        normals,
        band_radius_px=int(config["boundary_band_radius_px"]),
    )
    inward_offsets = _inward_offsets_to_mask(
        contour,
        normals,
        robust_mask,
        max_shift_px=int(config["max_inward_shift_px"]),
    )
    smoothed_boundary_chroma = _circular_smooth(
        boundary_chroma,
        int(config["suspicion_smooth_window"]),
    )
    smoothed_signed_halo = _circular_smooth(
        signed_halo,
        int(config["suspicion_smooth_window"]),
    )
    smoothed_inward_offsets = _circular_smooth(
        inward_offsets,
        int(config["suspicion_smooth_window"]),
    )
    vertical_normal_weight = np.asarray(np.abs(normals[:, 1]), dtype=np.float32)
    suspicion_score = np.asarray(
        smoothed_signed_halo * smoothed_inward_offsets * np.maximum(vertical_normal_weight, 0.0),
        dtype=np.float32,
    )
    arc_lengths = _cumulative_arc_lengths(contour)
    candidate_flags = np.zeros(len(contour), dtype=bool)
    candidate_arcs = []
    for region_label, region_flags in _component_candidate_region_flags(
        component_kind=component_kind,
        contour=contour,
        normals=normals,
        config=config,
    ):
        for indexes in _contiguous_true_runs(region_flags):
            if len(indexes) < int(config["min_arc_point_count"]):
                continue
            for index in indexes:
                candidate_flags[int(index)] = True
            candidate_arcs.append(
                {
                    "indexes": list(indexes),
                    "point_count": int(len(indexes)),
                    "arc_length_px": float(_arc_length_from_indexes(contour, indexes)),
                    "max_score": float(max(suspicion_score[index] for index in indexes)),
                    "region_label": str(region_label),
                }
            )
    return {
        "contour": contour,
        "tangents": tangents,
        "normals": normals,
        "boundary_chroma": boundary_chroma,
        "signed_halo": signed_halo,
        "inward_offsets": inward_offsets,
        "smoothed_boundary_chroma": smoothed_boundary_chroma,
        "smoothed_signed_halo": smoothed_signed_halo,
        "smoothed_inward_offsets": smoothed_inward_offsets,
        "vertical_normal_weight": vertical_normal_weight,
        "suspicion_score": suspicion_score,
        "suspicious_flags": np.asarray(candidate_flags, dtype=bool),
        "candidate_flags": np.asarray(candidate_flags, dtype=bool),
        "suspicious_arcs": candidate_arcs,
        "candidate_arcs": candidate_arcs,
        "arc_lengths": arc_lengths,
    }


def _sample_normal_profile(
    *,
    point,
    normal,
    bgr_frame: np.ndarray,
    gray_frame: np.ndarray,
    halo_robust_gray: np.ndarray,
    radius_px: int,
) -> list[dict]:
    rows = []
    for offset in range(-int(radius_px), int(radius_px) + 1):
        sample_point = np.asarray(point, dtype=np.float32) + (np.asarray(normal, dtype=np.float32) * float(offset))
        b_value, g_value, r_value = _sample_bgr(bgr_frame, sample_point)
        rows.append(
            {
                "offset_px": int(offset),
                "x_px": float(sample_point[0]),
                "y_px": float(sample_point[1]),
                "gray": float(_sample_scalar(gray_frame, sample_point)),
                "halo_robust_gray": float(_sample_scalar(halo_robust_gray, sample_point)),
                "b": int(b_value),
                "g": int(g_value),
                "r": int(r_value),
                "abs_rb": float(abs(float(r_value) - float(b_value))),
                "signed_halo": float(_signed_halo_value(normal, b_value=b_value, r_value=r_value)),
            }
        )
    return rows


def _profile_inward_shift(
    profile_rows: list[dict],
    *,
    region_label: str,
    inward_offset_px: float,
    max_inward_shift_px: int,
    min_inside_signed_halo: float,
    min_outside_signed_halo: float,
    min_signed_halo_margin: float,
    min_transition: float,
) -> tuple[float, dict]:
    rows = [dict(row) for row in list(profile_rows or [])]
    outside_rows = [row for row in rows if int(row.get("offset_px") or 0) >= 0]
    inside_rows = [row for row in rows if int(row.get("offset_px") or 0) < 0]
    outside_signed = [max(0.0, float(row.get("signed_halo") or 0.0)) for row in outside_rows]
    inside_signed = [max(0.0, float(row.get("signed_halo") or 0.0)) for row in inside_rows]
    outside_mean = float(np.mean(outside_signed)) if outside_signed else 0.0
    inside_mean = float(np.mean(inside_signed)) if inside_signed else 0.0
    peak_row = max(rows, key=lambda row: float(row.get("signed_halo") or 0.0), default=None)
    peak_signed_halo = 0.0 if peak_row is None else float(peak_row.get("signed_halo") or 0.0)
    peak_offset_px = None if peak_row is None else int(peak_row.get("offset_px") or 0)

    offsets = [int(row.get("offset_px") or 0) for row in rows]
    robust_values = [float(row.get("halo_robust_gray") or 0.0) for row in rows]
    transition_shift = 0.0
    transition_strength = float(min_transition)
    for index in range(len(offsets) - 1):
        left_offset = int(offsets[index])
        if left_offset < -int(max_inward_shift_px) or left_offset > 0:
            continue
        transition = float(robust_values[index + 1] - robust_values[index])
        if transition > transition_strength:
            transition_strength = float(transition)
            transition_shift = float(max(0, -left_offset))

    gate_mode = "outside"
    if str(region_label) == "detached_top_cap":
        gate_mode = "inside"
        valid = bool(
            inside_mean >= float(min_inside_signed_halo)
            and (inside_mean - outside_mean) >= float(min_signed_halo_margin)
            and peak_signed_halo >= float(min_inside_signed_halo)
            and peak_offset_px is not None
            and peak_offset_px <= 0
        )
        shift_from_peak = 0.0 if peak_offset_px is None else float(max(0, -peak_offset_px))
        shift_candidate = max(float(inward_offset_px), float(transition_shift), float(shift_from_peak))
    else:
        valid = bool(
            outside_mean >= float(min_outside_signed_halo)
            and (outside_mean - inside_mean) >= float(min_signed_halo_margin)
            and peak_signed_halo >= float(min_outside_signed_halo)
            and peak_offset_px is not None
            and peak_offset_px >= 0
        )
        shift_from_peak = 0.0 if peak_offset_px is None else float(max(0, peak_offset_px))
        shift_candidate = max(float(inward_offset_px), float(transition_shift), float(shift_from_peak))
    shift = min(float(shift_candidate), float(max_inward_shift_px)) if valid else 0.0
    return float(shift), {
        "valid": bool(valid),
        "gate_mode": str(gate_mode),
        "outside_mean": float(outside_mean),
        "inside_mean": float(inside_mean),
        "outside_inside_margin": float(outside_mean - inside_mean),
        "inside_outside_margin": float(inside_mean - outside_mean),
        "peak_signed_halo": float(peak_signed_halo),
        "peak_offset_px": peak_offset_px,
        "shift_from_peak_px": float(0.0 if peak_offset_px is None else max(0, -peak_offset_px if gate_mode == "inside" else peak_offset_px)),
        "transition_shift_px": float(transition_shift),
        "transition_strength": float(transition_strength),
    }


def _candidate_sample_indexes(indexes: list[int], contour: np.ndarray, *, spacing_px: float) -> list[int]:
    if not indexes:
        return []
    selected = [int(indexes[0])]
    last_point = np.asarray(contour[indexes[0]], dtype=np.float32)
    for index in indexes[1:]:
        point = np.asarray(contour[index], dtype=np.float32)
        if float(np.linalg.norm(point - last_point)) >= float(spacing_px):
            selected.append(int(index))
            last_point = point
    if int(indexes[-1]) not in selected:
        selected.append(int(indexes[-1]))
    return selected


def _interpolate_arc_shift(indexes: list[int], sample_indexes: list[int], sample_shifts: list[float]) -> dict[int, float]:
    if not indexes:
        return {}
    if not sample_indexes:
        return {int(index): 0.0 for index in indexes}
    base_positions = {int(index): idx for idx, index in enumerate(indexes)}
    x_values = np.asarray([float(base_positions[int(index)]) for index in sample_indexes], dtype=np.float32)
    y_values = np.asarray([float(value) for value in sample_shifts], dtype=np.float32)
    if len(sample_indexes) == 1:
        return {int(index): float(y_values[0]) for index in indexes}
    full_positions = np.asarray([float(base_positions[int(index)]) for index in indexes], dtype=np.float32)
    interp = np.interp(full_positions, x_values, y_values).astype(np.float32)
    return {int(index): float(interp[idx]) for idx, index in enumerate(indexes)}


def _rasterize_contour(contour: np.ndarray, image_shape) -> np.ndarray:
    mask = np.zeros(image_shape[:2], dtype=np.uint8)
    if contour is None or len(contour) < 3:
        return mask
    polygon = np.asarray(np.round(contour), dtype=np.int32).reshape((-1, 1, 2))
    polygon[:, 0, 0] = np.clip(polygon[:, 0, 0], 0, image_shape[1] - 1)
    polygon[:, 0, 1] = np.clip(polygon[:, 0, 1], 0, image_shape[0] - 1)
    cv2.fillPoly(mask, [polygon], 255)
    return mask


def _component_color(kind: str) -> tuple[int, int, int]:
    return (0, 220, 255) if str(kind) == "attached" else (70, 220, 120)


def _apply_component_correction(
    *,
    component_entry: dict,
    suspicious_debug: dict,
    bgr_frame: np.ndarray,
    gray_frame: np.ndarray,
    halo_robust_gray: np.ndarray,
    roi: dict,
    frame_row: dict,
    config: dict,
) -> dict:
    contour_source = suspicious_debug.get("contour")
    contour = np.asarray([] if contour_source is None else contour_source, dtype=np.float32)
    if contour.size <= 0:
        return {
            "corrected_contour": component_entry.get("contour"),
            "corrected_mask": component_entry.get("full_mask"),
            "corrected_edge_rows": list(component_entry.get("edge_rows") or []),
            "corrected_volume_nl": float(component_entry.get("volume_nl") or 0.0),
            "sample_profiles": [],
            "moved_arc_length_px": 0.0,
            "max_inward_shift_px": 0.0,
            "boundary_chroma_before_stats": {"mean": None, "median": None, "max": None},
            "boundary_chroma_after_stats": {"mean": None, "median": None, "max": None},
            "suspicious_arc_count": 0,
        }

    normals = np.asarray(suspicious_debug["normals"], dtype=np.float32)
    shift_map = {index: 0.0 for index in range(len(contour))}
    sample_profiles = []
    for arc in list(suspicious_debug.get("suspicious_arcs") or []):
        indexes = list(arc.get("indexes") or [])
        region_label = str(arc.get("region_label") or "")
        sample_indexes = _candidate_sample_indexes(
            indexes,
            contour,
            spacing_px=float(config["sample_spacing_px"]),
        )
        raw_shifts = []
        for contour_index in sample_indexes:
            point = np.asarray(contour[int(contour_index)], dtype=np.float32)
            normal = np.asarray(normals[int(contour_index)], dtype=np.float32)
            profile_rows = _sample_normal_profile(
                point=point,
                normal=normal,
                bgr_frame=bgr_frame,
                gray_frame=gray_frame,
                halo_robust_gray=halo_robust_gray,
                radius_px=int(config["profile_radius_px"]),
            )
            inward_offset = float(suspicious_debug["inward_offsets"][int(contour_index)])
            proposed_shift, profile_gate = _profile_inward_shift(
                profile_rows,
                region_label=region_label,
                inward_offset_px=inward_offset,
                max_inward_shift_px=int(config["max_inward_shift_px"]),
                min_inside_signed_halo=float(config["profile_min_inside_signed_halo"]),
                min_outside_signed_halo=float(config["profile_min_outside_signed_halo"]),
                min_signed_halo_margin=float(config["profile_min_signed_halo_margin"]),
                min_transition=float(config["profile_min_transition"]),
            )
            raw_shifts.append(float(proposed_shift))
            sample_profiles.append(
                {
                    "component_kind": str(component_entry["component_kind"]),
                    "component_id": str(component_entry["component_id"]),
                    "region_label": region_label,
                    "contour_index": int(contour_index),
                    "point_x_px": float(point[0]),
                    "point_y_px": float(point[1]),
                    "raw_shift_px": float(proposed_shift),
                    "suspicion_score": float(suspicious_debug["suspicion_score"][int(contour_index)]),
                    "boundary_chroma": float(suspicious_debug["boundary_chroma"][int(contour_index)]),
                    "signed_halo": float(suspicious_debug["signed_halo"][int(contour_index)]),
                    "profile_halo_valid": bool(profile_gate["valid"]),
                    "profile_gate_mode": str(profile_gate["gate_mode"]),
                    "inward_offset_px": float(inward_offset),
                    "profile_outside_signed_halo": float(profile_gate["outside_mean"]),
                    "profile_inside_signed_halo": float(profile_gate["inside_mean"]),
                    "profile_signed_halo_margin": float(profile_gate["outside_inside_margin"]),
                    "profile_inside_signed_halo_margin": float(profile_gate["inside_outside_margin"]),
                    "profile_peak_signed_halo": float(profile_gate["peak_signed_halo"]),
                    "profile_peak_offset_px": profile_gate["peak_offset_px"],
                    "profile_shift_from_peak_px": float(profile_gate["shift_from_peak_px"]),
                    "profile_transition_shift_px": float(profile_gate["transition_shift_px"]),
                    "profile_transition_strength": float(profile_gate["transition_strength"]),
                    "rows": profile_rows,
                }
            )
        smoothed = _median_smooth(raw_shifts, int(config["profile_smooth_window"]))
        for index, shift_value in _interpolate_arc_shift(indexes, sample_indexes, smoothed).items():
            shift_map[int(index)] = max(float(shift_map.get(int(index), 0.0)), float(shift_value))

    corrected_contour = np.asarray(contour, dtype=np.float32).copy()
    moved_flags = []
    for index in range(len(corrected_contour)):
        inward_shift = float(shift_map.get(index, 0.0))
        moved_flags.append(bool(inward_shift > 0.0))
        if inward_shift <= 0.0:
            continue
        corrected_contour[index] = corrected_contour[index] - (normals[index] * float(inward_shift))

    corrected_mask = _rasterize_contour(corrected_contour, bgr_frame.shape)
    if not np.any(corrected_mask > 0):
        fallback_mask = component_entry.get("full_mask")
        corrected_mask = np.asarray(
            np.zeros(bgr_frame.shape[:2], dtype=np.uint8) if fallback_mask is None else fallback_mask
        ).copy()
        fallback_contour = component_entry.get("contour")
        corrected_contour = np.asarray(
            contour if fallback_contour is None else fallback_contour,
            dtype=np.float32,
        ).copy()
        moved_flags = [False for _ in range(len(contour))]
        shift_map = {index: 0.0 for index in range(len(contour))}

    local_mask = corrected_mask[int(roi["y0"]) : int(roi["y1"]), int(roi["x0"]) : int(roi["x1"])]
    corrected_edge_rows = silhouette_mod._trace_edges(
        local_mask,
        roi,
        frame_row,
        component_id=str(component_entry["component_id"]),
        component_role=str(component_entry["component"].get("component_role") or ""),
        component_rank=int(component_entry["component"].get("component_rank") or 0),
    )
    corrected_volume_nl = _edge_rows_volume_nl(corrected_edge_rows)

    corrected_boundary_chroma = _boundary_chroma_scores(
        bgr_frame,
        np.asarray(corrected_contour, dtype=np.float32),
        suspicious_debug["normals"],
        band_radius_px=int(config["boundary_band_radius_px"]),
    )
    suspicious_indexes = sorted(
        {
            int(index)
            for arc in list(suspicious_debug.get("suspicious_arcs") or [])
            for index in list(arc.get("indexes") or [])
        }
    )
    before_values = [float(suspicious_debug["boundary_chroma"][index]) for index in suspicious_indexes]
    after_values = [float(corrected_boundary_chroma[index]) for index in suspicious_indexes]

    moved_arc_length_px = 0.0
    for index in range(1, len(contour)):
        if bool(moved_flags[index]) and bool(moved_flags[index - 1]):
            moved_arc_length_px += float(
                np.linalg.norm(np.asarray(contour[index]) - np.asarray(contour[index - 1]))
            )
    if bool(moved_flags[0]) and bool(moved_flags[-1]) and len(contour) > 1:
        moved_arc_length_px += float(
            np.linalg.norm(np.asarray(contour[0]) - np.asarray(contour[-1]))
        )

    def _stats(values):
        numbers = [float(value) for value in list(values or [])]
        if not numbers:
            return {"mean": None, "median": None, "max": None}
        return {
            "mean": float(np.mean(numbers)),
            "median": float(np.median(numbers)),
            "max": float(np.max(numbers)),
        }

    return {
        "corrected_contour": corrected_contour,
        "corrected_mask": corrected_mask,
        "corrected_edge_rows": corrected_edge_rows,
        "corrected_volume_nl": float(corrected_volume_nl),
        "sample_profiles": sample_profiles,
        "moved_arc_length_px": float(moved_arc_length_px),
        "max_inward_shift_px": float(max((float(value) for value in shift_map.values()), default=0.0)),
        "boundary_chroma_before_stats": _stats(before_values),
        "boundary_chroma_after_stats": _stats(after_values),
        "suspicious_arc_count": int(len(suspicious_debug.get("suspicious_arcs") or [])),
        "shift_map": {str(key): float(value) for key, value in shift_map.items()},
        "moved_flags": [bool(item) for item in moved_flags],
    }


def _draw_contours(image: np.ndarray, contours: list[tuple[np.ndarray, tuple[int, int, int], int]]) -> np.ndarray:
    output = image.copy()
    for contour, color, thickness in list(contours or []):
        if contour is None or len(contour) < 2:
            continue
        poly = np.asarray(np.round(contour), dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(
            output,
            [poly],
            isClosed=True,
            color=tuple(int(v) for v in color),
            thickness=int(thickness),
            lineType=cv2.LINE_AA,
        )
    return output


def _draw_arc_segments(image: np.ndarray, contour: np.ndarray, indexes: list[int], color) -> np.ndarray:
    output = image.copy()
    if contour is None or len(indexes) < 2:
        return output
    points = np.asarray([contour[index] for index in indexes], dtype=np.int32).reshape((-1, 1, 2))
    cv2.polylines(
        output,
        [points],
        isClosed=False,
        color=tuple(int(v) for v in color),
        thickness=3,
        lineType=cv2.LINE_AA,
    )
    return output


def _accepted_correction_overlay(frame_bgr: np.ndarray, component_debug_rows: list[dict]) -> np.ndarray:
    overlay = frame_bgr.copy()
    for row in list(component_debug_rows or []):
        overlay = _draw_contours(
            overlay,
            [(row.get("baseline_contour"), (170, 170, 170), 1)],
        )
        corrected_contour = np.asarray(
            [] if row.get("corrected_contour") is None else row.get("corrected_contour"),
            dtype=np.float32,
        )
        moved_flags = np.asarray(list(row.get("moved_flags") or []), dtype=bool)
        if corrected_contour.size <= 0 or moved_flags.size <= 0 or not np.any(moved_flags):
            continue
        for indexes in _contiguous_true_runs(moved_flags):
            overlay = _draw_arc_segments(
                overlay,
                corrected_contour,
                list(indexes),
                (255, 255, 0),
            )
    return overlay


def _full_frame_scalar_visual(gray_frame: np.ndarray, halo_robust_gray: np.ndarray, roi: dict) -> np.ndarray:
    base = cv2.cvtColor(np.asarray(gray_frame, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    roi_view = cv2.cvtColor(np.asarray(halo_robust_gray, dtype=np.uint8), cv2.COLOR_GRAY2BGR)
    base[int(roi["y0"]) : int(roi["y1"]), int(roi["x0"]) : int(roi["x1"])] = roi_view[
        int(roi["y0"]) : int(roi["y1"]),
        int(roi["x0"]) : int(roi["x1"]),
    ]
    cv2.rectangle(
        base,
        (int(roi["x0"]), int(roi["y0"])),
        (int(roi["x1"]) - 1, int(roi["y1"]) - 1),
        (0, 255, 255),
        2,
    )
    return base


def _save_image(path: Path, image: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image)
    return path


def _select_representative_profiles(sample_profiles: list[dict], config: dict) -> list[dict]:
    if not sample_profiles:
        return []
    max_profiles = int(max(1, config["max_profiles"]))
    attached = [row for row in sample_profiles if str(row.get("component_kind")) == "attached"]
    detached = [row for row in sample_profiles if str(row.get("component_kind")) != "attached"]

    def _rank(rows):
        return sorted(
            list(rows or []),
            key=lambda row: (
                float(row.get("suspicion_score") or 0.0),
                float(row.get("raw_shift_px") or 0.0),
            ),
            reverse=True,
        )

    if attached and detached:
        attached_limit = max(1, max_profiles // 2)
        detached_limit = max(1, max_profiles - attached_limit)
        candidates = _rank(attached)[:attached_limit] + _rank(detached)[:detached_limit]
    else:
        candidates = _rank(sample_profiles)[:max_profiles]

    selected = []
    min_spacing = float(config["min_profile_spacing_px"])
    for row in candidates:
        point = np.asarray([float(row["point_x_px"]), float(row["point_y_px"])], dtype=np.float32)
        if any(
            float(
                np.linalg.norm(
                    point
                    - np.asarray([float(item["point_x_px"]), float(item["point_y_px"])], dtype=np.float32)
                )
            )
            < min_spacing
            for item in selected
        ):
            continue
        selected.append(dict(row))
        if len(selected) >= max_profiles:
            break
    if not selected:
        selected = [dict(candidates[0])]
    return selected


def _save_profile_plot(profile_row: dict, output_dir: Path) -> dict:
    import matplotlib.pyplot as plt

    rows = [dict(item) for item in list(profile_row.get("rows") or [])]
    output_dir.mkdir(parents=True, exist_ok=True)
    sequence = len(list(output_dir.glob("profile_*.csv"))) + 1
    csv_path = output_dir / f"profile_{sequence:02d}.csv"
    png_path = output_dir / f"profile_{sequence:02d}.png"
    _write_csv(csv_path, rows)

    offsets = [float(row["offset_px"]) for row in rows]
    gray_values = [float(row["gray"]) for row in rows]
    robust_values = [float(row["halo_robust_gray"]) for row in rows]
    chroma_values = [float(row["abs_rb"]) for row in rows]
    signed_halo_values = [float(row.get("signed_halo") or 0.0) for row in rows]
    raw_shift = float(profile_row.get("raw_shift_px") or 0.0)
    corrected_offset = -raw_shift
    profile_halo_valid = bool(profile_row.get("profile_halo_valid"))

    fig, axes = plt.subplots(2, 1, figsize=(8.5, 6.5), sharex=True)
    axes[0].plot(offsets, gray_values, marker="o", linewidth=1.8, label="gray")
    axes[0].plot(offsets, robust_values, marker="o", linewidth=1.8, label="halo_robust_gray")
    axes[0].axvline(0.0, color="black", linestyle="--", linewidth=1.0, label="baseline edge")
    axes[0].axvline(corrected_offset, color="tab:green", linestyle=":", linewidth=1.2, label="corrected edge")
    axes[0].set_ylabel("Intensity")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(loc="best", fontsize=8)
    axes[0].set_title(
        f"{profile_row['component_kind']} {profile_row['component_id']} {profile_row.get('region_label') or 'candidate'} idx={profile_row['contour_index']} shift={raw_shift:.2f}px valid={profile_halo_valid}"
    )

    axes[1].plot(offsets, chroma_values, marker="o", linewidth=1.8, color="tab:orange", label="abs(R-B)")
    axes[1].plot(offsets, signed_halo_values, marker="o", linewidth=1.6, color="tab:green", label="signed halo")
    axes[1].axvline(0.0, color="black", linestyle="--", linewidth=1.0)
    axes[1].axvline(corrected_offset, color="tab:green", linestyle=":", linewidth=1.2)
    axes[1].set_xlabel("Offset along contour normal (px)")
    axes[1].set_ylabel("Chroma / signed halo")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(png_path, dpi=180)
    plt.close(fig)
    return {
        "component_kind": str(profile_row["component_kind"]),
        "component_id": str(profile_row["component_id"]),
        "region_label": str(profile_row.get("region_label") or ""),
        "contour_index": int(profile_row["contour_index"]),
        "raw_shift_px": float(raw_shift),
        "csv_path": str(csv_path),
        "plot_path": str(png_path),
    }


def _build_bundle_summary(
    *,
    context: dict,
    baseline_analysis: dict,
    robust_analysis: dict,
    component_debug_rows: list[dict],
) -> dict:
    baseline_summary = dict((baseline_analysis.get("runtime_result") or {}).get("summary") or {})
    baseline_stage4 = dict((baseline_analysis.get("stage4_frame") or {}).get("frame_metric_row") or {})
    robust_stage4 = dict((robust_analysis.get("stage4_frame") or {}).get("frame_metric_row") or {})

    corrected_attached_volume = float(
        sum(float(row["corrected_volume_nl"]) for row in component_debug_rows if str(row["component_kind"]) == "attached")
    )
    corrected_detached_volume = float(
        sum(float(row["corrected_volume_nl"]) for row in component_debug_rows if str(row["component_kind"]) != "attached")
    )
    corrected_total_volume = float(corrected_attached_volume + corrected_detached_volume)
    baseline_total_volume = float(baseline_stage4.get("total_visible_volume_nl") or 0.0)
    before_values = [
        float(item)
        for row in component_debug_rows
        for item in [row["boundary_chroma_before_stats"].get("mean")]
        if item is not None
    ]
    after_values = [
        float(item)
        for row in component_debug_rows
        for item in [row["boundary_chroma_after_stats"].get("mean")]
        if item is not None
    ]
    return {
        "analysis": ANALYSIS_NAME,
        "run_id": str(context["run_id"]),
        "capture_id": str(context["capture_id"]),
        "delay_us": int(context["delay_us"]),
        "delay_from_emergence_us": int(context["delay_us"] - context["emergence_time_us"]),
        "image_path": str(context["image_path"]),
        "background_path": None if context.get("background_path") is None else str(context["background_path"]),
        "nozzle_center_px": list(context["nozzle_center_px"]),
        "emergence_time_us": int(context["emergence_time_us"]),
        "baseline_visible_volume_nl": baseline_total_volume,
        "baseline_attached_volume_nl": float(baseline_stage4.get("attached_visible_volume_nl") or 0.0),
        "baseline_detached_volume_nl": float(baseline_stage4.get("detached_visible_volume_nl") or 0.0),
        "halo_robust_visible_volume_nl": float(robust_stage4.get("total_visible_volume_nl") or 0.0),
        "corrected_visible_volume_nl": float(corrected_total_volume),
        "corrected_attached_volume_nl": float(corrected_attached_volume),
        "corrected_detached_volume_nl": float(corrected_detached_volume),
        "volume_delta_nl": float(corrected_total_volume - baseline_total_volume),
        "moved_arc_length_px": float(sum(float(row["moved_arc_length_px"]) for row in component_debug_rows)),
        "max_inward_shift_px": float(max((float(row["max_inward_shift_px"]) for row in component_debug_rows), default=0.0)),
        "suspicious_arc_counts": {
            str(row["component_id"]): int(row["suspicious_arc_count"])
            for row in component_debug_rows
        },
        "boundary_chroma_before_stats": {
            "mean": None if not before_values else float(np.mean(before_values)),
            "median": None if not before_values else float(np.median(before_values)),
            "max": None if not before_values else float(np.max(before_values)),
        },
        "boundary_chroma_after_stats": {
            "mean": None if not after_values else float(np.mean(after_values)),
            "median": None if not after_values else float(np.median(after_values)),
            "max": None if not after_values else float(np.max(after_values)),
        },
        "baseline_summary": baseline_summary,
    }


def export_online_halo_debug_bundle(
    experiment_root,
    run_id,
    capture_id,
    *,
    output_root=None,
    config: dict | None = None,
) -> dict:
    resolved_config = _resolved_config(config)
    context = _load_frame_context(experiment_root, run_id, capture_id)
    resolved_output_root = _output_root(context["experiment_root"], run_id, capture_id, output_root=output_root)
    resolved_output_root.mkdir(parents=True, exist_ok=True)

    baseline_analysis = _analyze_stage3_stage4(
        frame_image=context["frame_image"],
        background_image=context["background_image"],
        nozzle_center_px=context["nozzle_center_px"],
        delay_us=int(context["delay_us"]),
        emergence_time_us=int(context["emergence_time_us"]),
        analysis_config=context.get("analysis_config"),
        capture_ref=context.get("capture_ref"),
        capture_index=context.get("capture_index"),
    )
    frame_bgr = runtime_mod._coerce_bgr_frame(context["frame_image"], color_order="bgr")
    gray_frame = np.asarray(baseline_analysis["gray_frame"], dtype=np.uint8)
    rb_gap = np.abs(frame_bgr[:, :, 2].astype(np.float32) - frame_bgr[:, :, 0].astype(np.float32))
    halo_robust_gray = np.clip(
        gray_frame.astype(np.float32) + (float(resolved_config["lambda_rb"]) * rb_gap),
        0.0,
        255.0,
    ).astype(np.uint8)
    robust_analysis = _analyze_stage3_stage4(
        frame_image=context["frame_image"],
        background_image=context["background_image"],
        nozzle_center_px=context["nozzle_center_px"],
        delay_us=int(context["delay_us"]),
        emergence_time_us=int(context["emergence_time_us"]),
        analysis_config=context.get("analysis_config"),
        capture_ref=context.get("capture_ref"),
        capture_index=context.get("capture_index"),
        gray_override=halo_robust_gray,
    )

    baseline_stage3 = baseline_analysis["stage3_frame"]
    baseline_stage4 = baseline_analysis["stage4_frame"]
    robust_stage3 = robust_analysis["stage3_frame"]
    roi = dict(baseline_stage3.get("roi") or {})
    baseline_components = _component_entries(baseline_stage3, baseline_stage4, image_shape=frame_bgr.shape)
    robust_components = _component_entries(robust_stage3, robust_analysis["stage4_frame"], image_shape=frame_bgr.shape)
    robust_map = {entry["component_key"]: entry for entry in robust_components}

    component_debug_rows = []
    for baseline_component in baseline_components:
        robust_component = robust_map.get(baseline_component["component_key"])
        suspicious_debug = _detect_suspicious_arcs(
            component_kind=str(baseline_component["component_kind"]),
            contour=baseline_component.get("contour"),
            mask=baseline_component.get("full_mask"),
            robust_mask=None if robust_component is None else robust_component.get("full_mask"),
            centroid=baseline_component.get("centroid"),
            bgr_frame=frame_bgr,
            config=resolved_config,
        )
        correction_debug = _apply_component_correction(
            component_entry=baseline_component,
            suspicious_debug=suspicious_debug,
            bgr_frame=frame_bgr,
            gray_frame=gray_frame,
            halo_robust_gray=halo_robust_gray,
            roi=roi,
            frame_row=runtime_mod._frame_row(
                delay_us=int(context["delay_us"]),
                emergence_time_us=int(context["emergence_time_us"]),
                capture_ref=context.get("capture_ref"),
                capture_index=context.get("capture_index"),
            ),
            config=resolved_config,
        )
        component_debug_rows.append(
            {
                "component_id": str(baseline_component["component_id"]),
                "component_kind": str(baseline_component["component_kind"]),
                "baseline_contour": baseline_component.get("contour"),
                "corrected_contour": correction_debug.get("corrected_contour"),
                "suspicious_debug": suspicious_debug,
                **correction_debug,
            }
        )

    if not any(list(row.get("sample_profiles") or []) for row in component_debug_rows):
        for row in component_debug_rows:
            contour = np.asarray(row.get("baseline_contour") if row.get("baseline_contour") is not None else [], dtype=np.float32)
            suspicion_score = np.asarray(row["suspicious_debug"].get("suspicion_score"), dtype=np.float32)
            normals = np.asarray(row["suspicious_debug"].get("normals"), dtype=np.float32)
            if contour.size <= 0 or suspicion_score.size <= 0 or normals.size <= 0:
                continue
            contour_index = int(np.argmax(suspicion_score))
            point = np.asarray(contour[contour_index], dtype=np.float32)
            normal = np.asarray(normals[contour_index], dtype=np.float32)
            row.setdefault("sample_profiles", []).append(
                {
                    "component_kind": str(row["component_kind"]),
                    "component_id": str(row["component_id"]),
                    "region_label": "",
                    "contour_index": int(contour_index),
                    "point_x_px": float(point[0]),
                    "point_y_px": float(point[1]),
                    "raw_shift_px": 0.0,
                    "suspicion_score": float(suspicion_score[contour_index]),
                    "boundary_chroma": float(row["suspicious_debug"]["boundary_chroma"][contour_index]),
                    "rows": _sample_normal_profile(
                        point=point,
                        normal=normal,
                        bgr_frame=frame_bgr,
                        gray_frame=gray_frame,
                        halo_robust_gray=halo_robust_gray,
                        radius_px=int(resolved_config["profile_radius_px"]),
                    ),
                }
            )
            break

    baseline_overlay = _draw_contours(
        frame_bgr,
        [
            (row["baseline_contour"], _component_color(row["component_kind"]), 2)
            for row in component_debug_rows
        ]
        + [
            (row["corrected_contour"], (255, 255, 0), 2)
            for row in component_debug_rows
        ],
    )
    suspicious_overlay = frame_bgr.copy()
    for row in component_debug_rows:
        suspicious_overlay = _draw_contours(
            suspicious_overlay,
            [(row["baseline_contour"], (170, 170, 170), 1)],
        )
        for arc in list(row["suspicious_debug"].get("suspicious_arcs") or []):
            suspicious_overlay = _draw_arc_segments(
                suspicious_overlay,
                np.asarray(row["baseline_contour"], dtype=np.float32),
                list(arc.get("indexes") or []),
                _component_color(row["component_kind"]),
            )

    accepted_overlay = _accepted_correction_overlay(frame_bgr, component_debug_rows)
    scalar_visual = _full_frame_scalar_visual(gray_frame, halo_robust_gray, roi)

    representative_profiles = _select_representative_profiles(
        [
            dict(sample)
            for row in component_debug_rows
            for sample in list(row.get("sample_profiles") or [])
        ],
        resolved_config,
    )
    profiles_dir = resolved_output_root / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_outputs = [_save_profile_plot(profile, profiles_dir) for profile in representative_profiles]

    summary = _build_bundle_summary(
        context=context,
        baseline_analysis=baseline_analysis,
        robust_analysis=robust_analysis,
        component_debug_rows=component_debug_rows,
    )

    overlay_path = _save_image(resolved_output_root / "baseline_vs_corrected_overlay.png", baseline_overlay)
    suspicious_path = _save_image(resolved_output_root / "suspicious_arcs_overlay.png", suspicious_overlay)
    accepted_path = _save_image(resolved_output_root / "accepted_correction_overlay.png", accepted_overlay)
    scalar_path = _save_image(resolved_output_root / "halo_robust_scalar.png", scalar_visual)
    frame_summary_path = _write_json(resolved_output_root / "frame_summary.json", summary)

    manifest = {
        "analysis": ANALYSIS_NAME,
        "run_id": str(run_id),
        "capture_id": str(capture_id),
        "output_root": str(resolved_output_root),
        "config": dict(resolved_config),
        "paths": {
            "frame_summary_json": str(frame_summary_path),
            "baseline_vs_corrected_overlay_png": str(overlay_path),
            "suspicious_arcs_overlay_png": str(suspicious_path),
            "accepted_correction_overlay_png": str(accepted_path),
            "halo_robust_scalar_png": str(scalar_path),
            "profiles_dir": str(profiles_dir),
        },
        "profile_outputs": profile_outputs,
        "component_debug": [
            {
                "component_id": str(row["component_id"]),
                "component_kind": str(row["component_kind"]),
                "suspicious_arc_count": int(row["suspicious_arc_count"]),
                "moved_arc_length_px": float(row["moved_arc_length_px"]),
                "max_inward_shift_px": float(row["max_inward_shift_px"]),
                "boundary_chroma_before_stats": row["boundary_chroma_before_stats"],
                "boundary_chroma_after_stats": row["boundary_chroma_after_stats"],
            }
            for row in component_debug_rows
        ],
    }
    manifest_path = _write_json(resolved_output_root / "bundle_manifest.json", manifest)
    manifest["paths"]["bundle_manifest_json"] = str(manifest_path)
    return manifest
